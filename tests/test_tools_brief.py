"""End-to-end smoke for director_brief_* MCP tools.

Verifies that calling `director_brief_read` and `director_brief_update` over the
MCP Streamable-HTTP transport with a valid bearer + directorRunId header:

1. Forwards GET/PATCH to the WM Studio backend at WMSTUDIO_API_URL/api/director/[runId]/brief
2. Sends x-director-run-id header for authentication
3. Returns the WM Studio JSON payload to the MCP client unchanged
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from src.auth import create_test_token
from src.config import get_settings
from src.server import root_app


WMSTUDIO_BASE = "http://localhost:3000"
RUN_ID = "run-abc-123"


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
async def test_director_brief_read_forwards_to_wmstudio(monkeypatch):
    monkeypatch.setenv("WMSTUDIO_API_URL", WMSTUDIO_BASE)
    get_settings.cache_clear()

    token = create_test_token(user_id="user-xyz")

    # Patch redis_client used by AuthGuardMiddleware
    from src.middleware import auth_guard as guard_mod

    fake_redis = _FakeRedis()
    monkeypatch.setattr(guard_mod, "_redis_from_app_state", lambda _req: fake_redis)

    # Mock the WM Studio Next.js route. Capture the request to assert headers.
    captured: dict = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content.decode() or "{}")
        return httpx.Response(
            200,
            json={
                "brief": {
                    "runId": RUN_ID,
                    "userId": "user-xyz",
                    "version": 1,
                    "sections": {
                        "logline": "A test logline",
                        "creativeBrief": "Test creative brief",
                    },
                    "createdAt": "2024-01-01T00:00:00Z",
                    "updatedAt": "2024-01-01T00:00:00Z",
                }
            },
        )

    with respx.mock(base_url=WMSTUDIO_BASE, assert_all_called=True) as mock:
        mock.get(f"/api/director/{RUN_ID}/brief").mock(side_effect=_capture)

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
            # tools/call director_brief_read
            r = client.post(
                "/mcp/",
                headers=sess_headers,
                json={
                    "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {
                        "name": "director_brief_read",
                        "arguments": {"director_run_id": RUN_ID},
                    },
                },
            )
            assert r.status_code == 200, r.text

    # 1. The x-director-run-id header was sent for authentication
    assert "x-director-run-id" in captured["headers"]
    assert captured["headers"]["x-director-run-id"] == RUN_ID
    # 2. The MCP tool result includes WM Studio's payload
    body = _parse_sse_or_json(r.text)
    result = body["result"]
    structured = result.get("structuredContent") or json.loads(result["content"][0]["text"])
    assert structured["brief"]["runId"] == RUN_ID
    assert structured["brief"]["version"] == 1


@pytest.mark.asyncio
async def test_director_brief_update_forwards_to_wmstudio(monkeypatch):
    monkeypatch.setenv("WMSTUDIO_API_URL", WMSTUDIO_BASE)
    get_settings.cache_clear()

    token = create_test_token(user_id="user-xyz")

    from src.middleware import auth_guard as guard_mod

    monkeypatch.setattr(
        guard_mod,
        "_redis_from_app_state",
        lambda _r: _FakeRedis(),
    )

    captured: dict = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content.decode() or "{}")
        return httpx.Response(
            200,
            json={
                "brief": {
                    "runId": RUN_ID,
                    "userId": "user-xyz",
                    "version": 2,
                    "sections": {
                        "logline": "Updated logline",
                        "creativeBrief": "Test creative brief",
                    },
                    "createdAt": "2024-01-01T00:00:00Z",
                    "updatedAt": "2024-01-01T01:00:00Z",
                }
            },
        )

    with respx.mock(base_url=WMSTUDIO_BASE, assert_all_called=True) as mock:
        mock.patch(f"/api/director/{RUN_ID}/brief").mock(side_effect=_capture)

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
            assert r.status_code == 200
            session_id = r.headers["mcp-session-id"]
            sess_headers = {**headers, "mcp-session-id": session_id}
            client.post(
                "/mcp/",
                headers=sess_headers,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            )
            # tools/call director_brief_update
            r = client.post(
                "/mcp/",
                headers=sess_headers,
                json={
                    "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {
                        "name": "director_brief_update",
                        "arguments": {
                            "director_run_id": RUN_ID,
                            "sections": {"logline": "Updated logline"},
                            "expected_version": 1,
                            "reason": "Updated the logline based on user feedback",
                        },
                    },
                },
            )
            assert r.status_code == 200, r.text

    # 1. The x-director-run-id header was sent for authentication
    assert "x-director-run-id" in captured["headers"]
    assert captured["headers"]["x-director-run-id"] == RUN_ID
    # 2. The patch payload was passed through
    assert captured["body"]["sections"]["logline"] == "Updated logline"
    assert captured["body"]["expectedVersion"] == 1
    assert captured["body"]["directorRunId"] == RUN_ID
    # 3. The MCP tool result includes WM Studio's payload
    body = _parse_sse_or_json(r.text)
    result = body["result"]
    structured = result.get("structuredContent") or json.loads(result["content"][0]["text"])
    assert structured["brief"]["runId"] == RUN_ID
    assert structured["brief"]["version"] == 2
