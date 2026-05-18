"""Async HTTP client for the WM Studio Next.js backend.

Forwards the user's upstream Supabase access token (obtained during the
MCP OAuth flow and cached in Redis at `mcp:upstream:<hash>`) to WM Studio
API routes as a `Bearer` header. WM Studio's `createServerSupabaseUserClient`
accepts Authorization headers in addition to cookies, so server-to-server
calls work without any cookie shenanigans.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

log = structlog.get_logger(__name__)


class WMStudioClientError(Exception):
    def __init__(self, status_code: int, message: str, payload: Any = None) -> None:
        self.status_code = status_code
        self.message = message
        self.payload = payload
        super().__init__(f"{status_code}: {message}")


class InsufficientCreditsError(WMStudioClientError):
    """Raised on HTTP 402 with `requiresTopUp: true`.

    `payload` carries the wmstudio response body — typically includes
    `requiredCredits`, `availableCredits`, `model`, and a friendly message.
    """


class WMStudioClient:
    """Thin wrapper around httpx targeting the WM Studio Next.js API."""

    def __init__(self, base_url: str, user_supabase_token: str, *, timeout: float = 300.0) -> None:
        self._base = base_url.rstrip("/")
        self._token = user_supabase_token.strip()
        # Long timeout: fal.ai sync image/video calls can run 30-180s.
        self._client = httpx.AsyncClient(
            base_url=self._base,
            timeout=httpx.Timeout(timeout, connect=10.0),
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "mcp-director/studio-tools",
            },
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def _parse(self, resp: httpx.Response, ctx: str) -> dict[str, Any]:
        raw = (resp.text or "").strip()
        content_type = (resp.headers.get("content-type") or "").lower()
        is_html = (
            "text/html" in content_type
            or raw.startswith("<!DOCTYPE")
            or raw.startswith("<html")
            or raw.startswith("<script")
        )
        if resp.status_code >= 400:
            payload: Any = None
            if not is_html:
                try:
                    payload = json.loads(raw) if raw else None
                except json.JSONDecodeError:
                    payload = None
            # OAuth 2 §5: 402 + `requiresTopUp: true` is wmstudio's signal that
            # the user can't afford this generation. Surface as a typed error
            # so tools can return a structured upgrade response.
            if resp.status_code == 402 and isinstance(payload, dict) and payload.get("requiresTopUp"):
                msg = str(payload.get("message") or payload.get("error") or "insufficient credits")
                raise InsufficientCreditsError(402, f"{ctx}: {msg}", payload)
            if is_html and resp.status_code == 404:
                # Most common cause: a Next.js route that doesn't exist on the
                # currently-deployed wmstudio container (e.g. mid-deploy swap).
                msg = (
                    "endpoint not found on wmstudio — route may not be deployed yet "
                    "or WMSTUDIO_API_URL points at the wrong host"
                )
            elif is_html:
                msg = f"wmstudio returned an HTML page (likely an error page) — {resp.reason_phrase}"
            else:
                msg = (
                    (payload or {}).get("error")
                    or (payload or {}).get("message")
                    or raw[:300]
                    or resp.reason_phrase
                )
            raise WMStudioClientError(resp.status_code, f"{ctx}: {msg}", payload)
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise WMStudioClientError(
                resp.status_code, f"{ctx}: non-JSON response: {raw[:160]!r}"
            ) from e
        if not isinstance(data, dict):
            raise WMStudioClientError(
                resp.status_code, f"{ctx}: expected JSON object, got {type(data).__name__}"
            )
        return data

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1.0, max=8),
        retry=retry_if_exception_type(httpx.HTTPStatusError),
    )
    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        resp = await self._client.request(method, url, **kwargs)
        # Retry only on 502/503/504 (transient infrastructure) and 429.
        if resp.status_code in (429, 502, 503, 504):
            resp.raise_for_status()
        return resp

    async def generate_image(self, payload: dict[str, Any]) -> dict[str, Any]:
        resp = await self._request("POST", "/api/creative-studio/generate-image", json=payload)
        return self._parse(resp, "generate_image")

    async def generate_video(self, payload: dict[str, Any]) -> dict[str, Any]:
        resp = await self._request("POST", "/api/creative-studio/generate-video", json=payload)
        return self._parse(resp, "generate_video")

    async def upscale_video(self, payload: dict[str, Any]) -> dict[str, Any]:
        resp = await self._request("POST", "/api/creative-studio/upscale-video", json=payload)
        return self._parse(resp, "upscale_video")

    async def get_job(self, job_id: str) -> dict[str, Any]:
        resp = await self._request("GET", f"/api/jobs/{job_id}")
        return self._parse(resp, "get_job")

    async def credits_balance(self) -> dict[str, Any]:
        resp = await self._request("GET", "/api/credits/balance")
        return self._parse(resp, "credits_balance")

    async def estimate_pricing(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Get a credit-cost estimate for a generation BEFORE running it.

        `payload` must include `model` plus any model-specific knobs that
        affect price (`duration`, `resolution`, `num_images`, `aspect_ratio`,
        ...). Returns `{ credits, costUSD, costEUR }`.
        """
        resp = await self._request("POST", "/api/creative-studio/pricing", json=payload)
        return self._parse(resp, "estimate_pricing")

    async def web_search(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Run a Tavily-powered web search via the WM Studio backend.

        `payload`: `{ query, maxResults?, searchDepth?, timeRange?,
                      includeDomains?, excludeDomains? }`.

        Returns `{ v: 1, answer, results, images, followUpQuestions,
        creditsCharged, creditsRemaining }`. Charges 1 credit (basic) or
        2 credits (advanced). Failed searches do not charge.
        """
        resp = await self._request("POST", "/api/me/tools/web-search", json=payload)
        return self._parse(resp, "web_search")


def get_user_wmstudio_client(ctx_request_state: Any, base_url: str) -> WMStudioClient:
    """Build a per-request WMStudioClient from the upstream Supabase token.

    The MCP `AuthGuardMiddleware` already populates `request.state.director_bearer_token`
    with the Supabase access token paired to the MCP JWT (via Redis `mcp:upstream:*`).
    We reuse that for WM Studio calls since both share the same Supabase auth backend.
    """
    upstream = getattr(ctx_request_state, "director_bearer_token", None)
    if not upstream:
        raise WMStudioClientError(
            401,
            "no upstream Supabase token attached to this MCP session — re-authenticate",
        )
    return WMStudioClient(base_url, upstream)
