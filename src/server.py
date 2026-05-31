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
from src.tools import assets, creative, insights, pipeline, studio, brief, reference_descriptions
from src.tools.registry import registry
from src.orchestrator import get_orchestrator, AgentMode

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
        "You are a video production agent powered by WM Studio with an orchestrator system.\n\n"
        "ORCHESTRATOR MODE:\n"
        "  The system uses an orchestrator to coordinate specialized agents:\n"
        "  - Casting Agent: Character sheets (3x1 panels, 16:9 aspect ratio)\n"
        "  - Storyboard Agent: Frame candidates for scenes\n"
        "  - Video Agent: Video generation from storyboard frames\n"
        "  - Reference Manager: Tracks characters, locations, props for consistency\n\n"
        "AUTO-CONTINUATION:\n"
        "  When the orchestrator is in AUTO mode, continue automatically after each action.\n"
        "  When in ASK mode, wait for user confirmation before continuing.\n"
        "  Current mode is determined by the user's initial request or explicit setting.\n\n"
        "CHARACTER SHEETS (Casting):\n"
        "  - Must generate 3x1 grid with 3 panels: macro (close-up), side profile, full body\n"
        "  - Fixed aspect ratio: 16:9 for the overall sheet\n"
        "  - Use studio_casting tool with character details\n"
        "  - Characters are automatically stored for later scene reference\n\n"
        "STORYBOARD WORKFLOW:\n"
        "  [1] Ask for aspect ratio (REQUIRED first step)\n"
        "  [2] studio_storyboard_frames(prompt, aspect_ratio, n=3, confirm=false) — cost preview\n"
        "  [3] Show estimatedCredits, ask 'Proceed?', wait for explicit yes\n"
        "  [4] studio_storyboard_frames(... confirm=true) — generates frames\n"
        "  [5] Wait for user to choose a frame (click or type number)\n"
        "  [6] If characters exist in memory, include them in scene prompts\n\n"
        "VIDEO GENERATION:\n"
        "  [1] studio_generate_video(prompt, image_url=<chosen frame>, confirm=false)\n"
        "  [2] Show estimatedCredits, ask 'Proceed?', wait for explicit yes\n"
        "  [3] studio_generate_video(... confirm=true) — generates video\n\n"
        "HARD RULES:\n"
        "  - STORYBOARD FIRST. Never call studio_generate_video without image_url.\n"
        "  - ALWAYS PREVIEW BEFORE CHARGING. confirm=false first, show cost, wait for approval.\n"
        "  - CHARACTER CONSISTENCY. When scenes include known characters, reference them.\n"
        "  - NEVER FABRICATE DATA. No invented URLs, IDs, credit amounts, or frame counts.\n"
        "  - INLINE RENDERING. The MCP App viewer renders everything. Trust it.\n"
        "  - CREDITS TRANSPARENCY. Show creditsCharged + creditsRemaining after each generation.\n"
        "  - ASSETS IN BRIEF. Generated assets automatically appear in the brief asset tab.\n"
        "  - TOOL ERRORS. Report exact error, do not retry silently.\n"
    ),
    version="1.0.0",
    middleware=[
        ErrorHandlingMiddleware(transform_errors=True),
        AuthGuardMiddleware(),
    ],
)

# Register legacy tools (will be migrated to plugins gradually)
pipeline.register(mcp)
creative.register(mcp)
assets.register(mcp)
insights.register(mcp)
studio.register(mcp)
brief.register(mcp)
reference_descriptions.register(mcp)
from src.tools import orchestrator_tools
orchestrator_tools.register(mcp)
register_resources(mcp)

# Initialize orchestrator and register agents
from src.agents import CastingAgent, StoryboardAgent, VideoAgent, ReferenceManager

orchestrator = get_orchestrator()
orchestrator.set_mode(AgentMode.ASK)  # Default to ASK mode for safety
orchestrator.register_agent("casting", CastingAgent())
orchestrator.register_agent("storyboard", StoryboardAgent())
orchestrator.register_agent("video", VideoAgent())
orchestrator.register_agent("reference_manager", ReferenceManager())

# Set orchestrator reference for each agent
for agent in orchestrator.agents.values():
    agent.set_orchestrator(orchestrator)

log.info("orchestrator_initialized", mode=orchestrator.mode.value, agents=list(orchestrator.agents.keys()))

# Discover and load plugins
registry.discover_plugins()

# Load and register plugin tools
async def load_and_register_plugins():
    """Load plugins and register their tools with MCP."""
    # Load all discovered plugins
    for plugin_name in list(registry._plugin_classes.keys()):
        plugin = registry.load_plugin(plugin_name)
        if plugin:
            await plugin.register_tools(mcp)
            log.info("plugin_tools_registered", plugin=plugin_name)

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
    
    # Load plugins on startup
    await load_and_register_plugins()
    
    try:
        async with mcp_app.router.lifespan_context(mcp_app):
            yield
    finally:
        # Close plugins on shutdown
        await registry.close_all()
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


@root_app.post("/api/director/cancel")
async def cancel_director_run(request: Request):
    """Cancel a Director run and stop any ongoing MCP tool executions."""
    try:
        body = await request.json()
        director_run_id = body.get("directorRunId")
        if not director_run_id:
            return JSONResponse({"error": "directorRunId required"}, status_code=400)

        redis = getattr(root_app.state, "redis", None)
        if not redis:
            log.error("cancel_director_run_no_redis")
            return JSONResponse({"error": "Redis not available"}, status_code=500)

        # Mark the run as cancelled in Redis
        key = f"cancelled_director_run:{director_run_id}"
        await redis.set(key, "1", ex=3600)  # Expire after 1 hour
        log.info("director_run_cancelled", director_run_id=director_run_id)

        return JSONResponse({"ok": True, "directorRunId": director_run_id})
    except Exception as e:
        log.error("cancel_director_run_failed", error=str(e))
        return JSONResponse({"error": str(e)}, status_code=500)


@root_app.get("/api/director/status/{director_run_id}")
async def get_director_run_status(director_run_id: str, request: Request):
    """Check if a Director run is cancelled."""
    try:
        redis = getattr(root_app.state, "redis", None)
        if not redis:
            return JSONResponse({"error": "Redis not available"}, status_code=500)

        key = f"cancelled_director_run:{director_run_id}"
        is_cancelled = await redis.exists(key)

        return JSONResponse({
            "directorRunId": director_run_id,
            "cancelled": bool(is_cancelled)
        })
    except Exception as e:
        log.error("get_director_run_status_failed", error=str(e))
        return JSONResponse({"error": str(e)}, status_code=500)


root_app.mount("/mcp", mcp_app)