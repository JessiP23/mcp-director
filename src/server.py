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
from src.auth import build_oauth_router
from src.config import get_settings
from src.middleware.auth_guard import AuthGuardMiddleware
from src.resources.templates import register_resources
from src.tools import assets, creative, insights, pipeline

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

@root_app.middleware("http")
async def _https_guard(request: Request, call_next):
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

@root_app.get("/health")
async def health():
    return {"status": "ok", "server": "director-mcp", "version": "1.0.0"}

@root_app.post("/webhooks/director")
async def director_webhook(request: Request):
    _ = await request.body()
    return JSONResponse({"received": True})

root_app.mount("/mcp", mcp_app)