"""Bearer JWT validation and per-user rate limiting for MCP operations."""

from __future__ import annotations

from typing import Any

import mcp.types as mt
from mcp import McpError
from mcp.types import ErrorData
from redis.asyncio import Redis

from fastmcp.server.dependencies import get_http_request
from fastmcp.server.middleware.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult

from src.auth import validate_mcp_token
from src.config import get_settings
from src.rate_limiter import RateLimiter


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

        return await call_next(context)

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        from fastmcp.server.context import _current_transport

        if _current_transport.get() == "stdio":
            return await call_next(context)
        request = get_http_request()
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
