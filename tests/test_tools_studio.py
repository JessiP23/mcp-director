"""End-to-end smoke for studio_* MCP tools.

Verifies that calling `studio_generate_image` over the MCP Streamable-HTTP
transport with a valid bearer + Redis-cached upstream Supabase token:

1. Forwards a POST to the WM Studio backend at WMSTUDIO_API_URL/api/creative-studio/generate-image
2. Sends `Authorization: Bearer <supabase_access>` (the upstream token, NOT the MCP JWT)
3. Returns the WM Studio JSON payload to the MCP client unchanged
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from src.auth import create_test_token, mcp_upstream_token_key
from src.config import get_settings
from src.server import root_app


WMSTUDIO_BASE = "http://localhost:3000"
UPSTREAM_SUPABASE_TOKEN = "supabase-upstream-token-fixture"


class _FakePipeline:
    def __init__(self) -> None:
        self._results: list = []

    def zremrangebyscore(self, *_a, **_kw):
        self._results.append(0)
        return self

    def zcard(self, *_a, **_kw):
        self._results.append(0)
        return self

    def zadd(self, *_a, **_kw):
        self._results.append(1)
        return self

    def expire(self, *_a, **_kw):
        self._results.append(True)
        return self

    async def execute(self) -> list:
        out, self._results = self._results, []
        return out


class _FakeRedis:
    """Minimal stand-in for redis.asyncio.Redis covering AuthGuard + RateLimiter."""

    def __init__(self, kv: dict[str, str] | None = None) -> None:
        self.kv = dict(kv or {})

    async def get(self, k: str):
        return self.kv.get(k)

    async def sismember(self, _set: str, _v: str) -> bool:
        return False

    def pipeline(self) -> _FakePipeline:
        return _FakePipeline()


def _parse_sse_or_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("{"):
        return json.loads(text)
    for line in text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    raise AssertionError(f"unparseable: {text[:200]!r}")


@pytest.mark.asyncio
async def test_studio_generate_image_forwards_to_wmstudio(monkeypatch):
    monkeypatch.setenv("WMSTUDIO_API_URL", WMSTUDIO_BASE)
    get_settings.cache_clear()

    token = create_test_token(user_id="user-xyz")
    # Mirror what /oauth/idp-callback -> /oauth/token does: stash the upstream
    # Supabase access token under mcp:upstream:<sha256(mcp_jwt)>.
    upstream_key = mcp_upstream_token_key(token)

    # Patch redis_client used by AuthGuardMiddleware to read upstream tokens.
    from src.middleware import auth_guard as guard_mod

    fake_redis = _FakeRedis({upstream_key: UPSTREAM_SUPABASE_TOKEN})
    monkeypatch.setattr(guard_mod, "_redis_from_app_state", lambda _req: fake_redis)

    # Mock the WM Studio Next.js route. Capture the request to assert headers.
    captured: dict = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization", "")
        captured["body"] = json.loads(request.content.decode() or "{}")
        return httpx.Response(
            200,
            json={
                "success": True,
                "imageUrl": "https://cdn.wmstudio.test/abc.png",
                "images": [{"url": "https://cdn.wmstudio.test/abc.png"}],
                "generationId": "gen_123",
                "requestId": "req_abc",
                "creditsCharged": 10,
            },
        )

    with respx.mock(base_url=WMSTUDIO_BASE, assert_all_called=True) as mock:
        mock.post("/api/creative-studio/generate-image").mock(side_effect=_capture)

        with TestClient(root_app) as client:
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            }
            # initialize
            r = client.post(
                "/mcp/",
                headers=headers,
                json={
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "t", "version": "0"},
                    },
                },
            )
            assert r.status_code == 200
            session_id = r.headers["mcp-session-id"]
            sess_headers = {**headers, "mcp-session-id": session_id}
            client.post(
                "/mcp/",
                headers=sess_headers,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            )
            # tools/call studio_generate_image
            r = client.post(
                "/mcp/",
                headers=sess_headers,
                json={
                    "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {
                        "name": "studio_generate_image",
                        "arguments": {
                            "prompt": "a cinematic neon alley at dusk",
                            "aspect_ratio": "16:9",
                        },
                    },
                },
            )
            assert r.status_code == 200, r.text

    # 1. The upstream Supabase token was forwarded as Bearer (NOT the MCP JWT).
    assert captured["authorization"] == f"Bearer {UPSTREAM_SUPABASE_TOKEN}"
    # 2. Prompt + aspect ratio were passed through.
    assert captured["body"]["prompt"] == "a cinematic neon alley at dusk"
    assert captured["body"]["aspect_ratio"] == "16:9"
    # 3. The MCP tool result includes WM Studio's payload.
    body = _parse_sse_or_json(r.text)
    result = body["result"]
    structured = result.get("structuredContent") or json.loads(result["content"][0]["text"])
    assert structured["imageUrl"] == "https://cdn.wmstudio.test/abc.png"
    assert structured["generationId"] == "gen_123"


@pytest.mark.asyncio
async def test_studio_job_status_forwards_to_wmstudio(monkeypatch):
    monkeypatch.setenv("WMSTUDIO_API_URL", WMSTUDIO_BASE)
    get_settings.cache_clear()

    token = create_test_token(user_id="user-xyz")
    upstream_key = mcp_upstream_token_key(token)

    from src.middleware import auth_guard as guard_mod

    monkeypatch.setattr(
        guard_mod,
        "_redis_from_app_state",
        lambda _r: _FakeRedis({upstream_key: UPSTREAM_SUPABASE_TOKEN}),
    )

    with respx.mock(base_url=WMSTUDIO_BASE, assert_all_called=True) as mock:
        mock.get("/api/jobs/job-42").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "job-42",
                    "status": "completed",
                    "progress": 100,
                    "resultUrl": "https://cdn.wmstudio.test/v.mp4",
                },
            ),
        )

        with TestClient(root_app) as client:
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            }
            r = client.post(
                "/mcp/",
                headers=headers,
                json={
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "t", "version": "0"},
                    },
                },
            )
            sess_headers = {**headers, "mcp-session-id": r.headers["mcp-session-id"]}
            client.post(
                "/mcp/",
                headers=sess_headers,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            )
            r = client.post(
                "/mcp/",
                headers=sess_headers,
                json={
                    "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {
                        "name": "studio_job_status",
                        "arguments": {"job_id": "job-42"},
                    },
                },
            )

    body = _parse_sse_or_json(r.text)
    result = body["result"]
    structured = result.get("structuredContent") or json.loads(result["content"][0]["text"])
    assert structured["status"] == "completed"
    assert structured["id"] == "job-42"
