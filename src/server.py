from __future__ import annotations
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from fastmcp import FastMCP
from fastmcp.server.middleware.error_handling import ErrorHandlingMiddleware
from src.auth import build_oauth_router, validate_mcp_token
from src.config import get_settings
from src.middleware.auth_guard import AuthGuardMiddleware
from src.resources.templates import register_resources
from src.tools import assets, creative, insights, pipeline

log = structlog.get_logger(__name__)

structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=False,
)

mcp = FastMCP(
    "director-mcp",
    instructions=(
        "AI video pipeline control — run, manage, and query director-cut productions"
    ),
    version="1.0.0",
    middleware=[
        ErrorHandlingMiddleware(transform_errors=True),
        AuthGuardMiddleware(),
    ],
)

pipeline.register(mcp)
creative.register(mcp)
assets.register(mcp)
insights.register(mcp)
register_resources(mcp)

mcp_app = mcp.http_app(
    path="/",
    transport="streamable-http",
    middleware=[
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=[
                "mcp-protocol-version",
                "mcp-session-id",
                "Authorization",
                "Content-Type",
            ],
            expose_headers=["mcp-session-id"],
        ),
    ],
)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    app.state.redis = redis
    mcp_app.state.redis = redis
    try:
        async with mcp_app.router.lifespan_context(mcp_app):
            yield
    finally:
        await redis.aclose()

root_app = FastAPI(title="director-mcp", lifespan=_lifespan)

root_app.include_router(build_oauth_router(), prefix="")

def _www_authenticate_header(settings) -> str:
    """RFC 6750 + RFC 9728 challenge advertising the resource metadata URL.

    Claude.ai (and other MCP clients) drive the OAuth flow off this header; without
    it, a missing/invalid bearer surfaces as a generic JSON-RPC error and the client
    never re-initiates auth.
    """
    base = settings.mcp_base_url.rstrip("/")
    return (
        f'Bearer realm="{settings.mcp_audience}", '
        f'resource_metadata="{base}/.well-known/oauth-protected-resource"'
    )


@root_app.middleware("http")
async def _https_guard(request: Request, call_next):
    # Starlette Mount("/mcp") only matches /mcp/{path}; bare /mcp never reaches MCP.
    # Clients (e.g. Claude UI) often omit the trailing slash — normalize before routing.
    if request.scope.get("type") == "http" and request.scope.get("path") == "/mcp":
        request.scope["path"] = "/mcp/"
    settings = get_settings()
    # Fly health checks hit :8080 over HTTP without X-Forwarded-Proto; rejecting
    # them breaks service checks and edge routing (PM05 intermittent failures).
    if request.url.path == "/health":
        return await call_next(request)
    if settings.environment == "production" or settings.enforce_https:
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        if proto != "https":
            return JSONResponse({"detail": "HTTPS required"}, status_code=400)
    return await call_next(request)


@root_app.middleware("http")
async def _mcp_bearer_gate(request: Request, call_next):
    """HTTP-level 401 with WWW-Authenticate for /mcp/* — MCP spec compliance.

    AuthGuardMiddleware (FastMCP layer) raises McpError on missing/invalid bearer,
    which the streamable-HTTP transport surfaces as a 200 with JSON-RPC error.
    Claude.ai's connector lib only re-initiates OAuth on a real HTTP 401 with
    WWW-Authenticate. This gate runs BEFORE the mounted MCP app and returns the
    spec-correct response so the client knows to re-auth.
    """
    path = request.scope.get("path", "")
    if not path.startswith("/mcp/"):
        return await call_next(request)
    if request.method == "OPTIONS":  # CORS preflight
        return await call_next(request)

    settings = get_settings()
    auth_header = request.headers.get("authorization", "")
    challenge = _www_authenticate_header(settings)

    if not auth_header.lower().startswith("bearer "):
        log.info(
            "mcp_request_missing_bearer",
            path=path,
            method=request.method,
            ua=request.headers.get("user-agent", "")[:80],
        )
        return JSONResponse(
            {"error": "unauthorized", "error_description": "Bearer token required"},
            status_code=401,
            headers={"WWW-Authenticate": challenge},
        )

    token = auth_header.split(" ", 1)[1].strip()
    redis = getattr(root_app.state, "redis", None)
    try:
        await validate_mcp_token(token, redis=redis)
    except ValueError as e:
        log.info(
            "mcp_request_invalid_bearer",
            path=path,
            method=request.method,
            reason=str(e),
            token_prefix=token[:12],
        )
        return JSONResponse(
            {
                "error": "invalid_token",
                "error_description": "The access token is invalid or expired.",
            },
            status_code=401,
            headers={
                "WWW-Authenticate": (
                    challenge + ', error="invalid_token", '
                    'error_description="The access token is invalid or expired."'
                )
            },
        )

    return await call_next(request)

@root_app.get("/health")
async def health():
    return {"status": "ok", "server": "director-mcp", "version": "1.0.0"}

@root_app.post("/webhooks/director")
async def director_webhook(request: Request):
    _ = await request.body()
    return JSONResponse({"received": True})

root_app.mount("/mcp", mcp_app)