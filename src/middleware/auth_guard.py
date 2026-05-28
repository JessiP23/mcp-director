"""Bearer JWT validation and per-user rate limiting for MCP operations."""

from __future__ import annotations

import time
from typing import Any

import mcp.types as mt
from mcp import McpError
from mcp.types import ErrorData
from redis.asyncio import Redis

from fastmcp.server.dependencies import get_http_request
from fastmcp.server.middleware.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult

import json

from src.auth import (
    _parse_upstream_entry,
    mcp_upstream_token_key,
    refresh_upstream_supabase_token,
    validate_mcp_token,
)
from src.client import _normalize_director_bearer_token
from src.config import get_settings
from src.rate_limiter import RateLimiter

# Refresh proactively when the upstream Supabase access token has < 2 minutes
# of life left. Tools may run for tens of seconds; this avoids in-flight expiry.
_UPSTREAM_REFRESH_SKEW_SECONDS = 120


def _redis_from_app_state(request: Any) -> Redis | None:
    app = getattr(request, "app", None)
    if app is None:
        return None
    return getattr(app.state, "redis", None)


class AuthGuardMiddleware(Middleware):
    """Validate director-mcp JWT, attach user to request.state; rate-limit tool calls."""

    async def on_request(
        self,
        context: MiddlewareContext[Any],
        call_next: CallNext[Any, Any],
    ) -> Any:
        from fastmcp.server.context import _current_transport

        if _current_transport.get() == "stdio":
            return await call_next(context)

        try:
            request = get_http_request()
        except RuntimeError:
            request = None

        if request is None:
            raise McpError(
                ErrorData(code=-32001, message="Missing HTTP request context")
            )

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise McpError(
                ErrorData(code=-32001, message="Missing Authorization header")
            )
        token = auth_header[7:]
        redis = _redis_from_app_state(request)
        try:
            claims = await validate_mcp_token(token, redis=redis)
        except ValueError:
            raise McpError(
                ErrorData(code=-32001, message="Invalid or expired token")
            ) from None

        request.state.user_id = claims["user_id"]
        request.state.scopes = claims["scopes"]
        request.state.bearer_token = token

        settings = get_settings()
        upstream: str | None = None
        if redis:
            upstream_key = mcp_upstream_token_key(token)
            raw = await redis.get(upstream_key)
            entry = _parse_upstream_entry(raw)
            if entry:
                now = int(time.time())
                exp = entry.get("exp") or 0
                # Refresh proactively if access token is near expiry AND we have a
                # refresh token. Legacy entries (exp=0) without refresh are used as-is.
                needs_refresh = (
                    exp > 0
                    and exp - now < _UPSTREAM_REFRESH_SKEW_SECONDS
                    and bool(entry.get("refresh"))
                )
                if needs_refresh:
                    refreshed = await refresh_upstream_supabase_token(
                        entry["refresh"], settings
                    )
                    if refreshed:
                        entry = refreshed
                        # Persist the rotated pair so the next request reuses it.
                        # Keep ~24h TTL — same horizon as the OAuth token endpoint.
                        await redis.setex(upstream_key, 86400, json.dumps(entry))
                upstream = _normalize_director_bearer_token(entry["access"])
        if (
            not upstream
            and settings.environment == "development"
            and settings.director_bearer_token.strip()
        ):
            upstream = _normalize_director_bearer_token(settings.director_bearer_token)
        request.state.director_bearer_token = upstream

        return await call_next(context)

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        from fastmcp.server.context import _current_transport
        import structlog

        log = structlog.get_logger(__name__)

        if _current_transport.get() == "stdio":
            return await call_next(context)
        request = get_http_request()
        
        # Extract Director metadata from tool arguments and store in request.state
        # The context has: copy, fastmcp_context, message, method, source, timestamp, type
        message = getattr(context, "message", None)
        log.info("on_call_tool_debug", message_type=type(message) if message else None)
        
        if message:
            log.info("on_call_tool_message", message=str(message)[:500])
            # Try to access arguments from the message
            # The message is a CallToolRequestParams object with an arguments attribute
            if hasattr(message, "arguments"):
                arguments = message.arguments
                log.info("on_call_tool_arguments", arguments=arguments)
                if isinstance(arguments, dict):
                    director_run_id = arguments.get("directorRunId")
                    director_event_id = arguments.get("directorEventId")
                    director_tool_name = arguments.get("directorToolName")
                    log.info(
                        "on_call_tool_director_metadata",
                        director_run_id=director_run_id,
                        director_event_id=director_event_id,
                        director_tool_name=director_tool_name,
                    )
                    if director_run_id and director_event_id and director_tool_name:
                        request.state.director_run_id = director_run_id
                        request.state.director_event_id = director_event_id
                        request.state.director_tool_name = director_tool_name
            elif isinstance(message, dict):
                arguments = message.get("params", {}).get("arguments", {})
                log.info("on_call_tool_arguments_from_dict", arguments=arguments)
                if isinstance(arguments, dict):
                    director_run_id = arguments.get("directorRunId")
                    director_event_id = arguments.get("directorEventId")
                    director_tool_name = arguments.get("directorToolName")
                    log.info(
                        "on_call_tool_director_metadata",
                        director_run_id=director_run_id,
                        director_event_id=director_event_id,
                        director_tool_name=director_tool_name,
                    )
                    if director_run_id and director_event_id and director_tool_name:
                        request.state.director_run_id = director_run_id
                        request.state.director_event_id = director_event_id
                        request.state.director_tool_name = director_tool_name
        
        redis = _redis_from_app_state(request)
        if redis:
            settings = get_settings()
            limiter = RateLimiter(redis, settings.rate_limit_calls_per_minute)
            uid = getattr(request.state, "user_id", None)
            if uid and not await limiter.check_and_increment(str(uid)):
                raise McpError(
                    ErrorData(
                        code=-32029,
                        message="Rate limit exceeded. Try again in a moment.",
                    )
                )
        return await call_next(context)
