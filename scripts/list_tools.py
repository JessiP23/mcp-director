"""Live tools/list smoke test against the in-process MCP app.

Runs the full Streamable-HTTP flow (initialize -> initialized -> tools/list)
against `src.server.root_app` using FastAPI's TestClient. No Fly deploy
required, no real Redis required (uses fakeredis if REDIS_URL is unset).

Usage:
    PYTHONPATH=. python scripts/list_tools.py
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

# Ensure tests can run without external services.
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "test-secret-do-not-use-in-prod-do-not-use")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("DIRECTOR_BASE_URL", "http://127.0.0.1:9420")
os.environ.setdefault("MCP_BASE_URL", "http://localhost:8080")

from fastapi.testclient import TestClient  # noqa: E402

from src.auth import create_test_token  # noqa: E402
from src.server import root_app  # noqa: E402


def _parse_sse_or_json(resp_text: str) -> dict[str, Any]:
    """Streamable-HTTP can return JSON or `event: message\\ndata: {...}` SSE frames."""
    text = resp_text.strip()
    if text.startswith("{"):
        return json.loads(text)
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            return json.loads(line[len("data:"):].strip())
    raise RuntimeError(f"Unparseable response: {text[:300]!r}")


def main() -> int:
    token = create_test_token()
    headers_base = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }

    with TestClient(root_app) as client:
        # 1) initialize
        init_resp = client.post(
            "/mcp/",
            headers=headers_base,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "list-tools-smoke", "version": "0.0.1"},
                },
            },
        )
        if init_resp.status_code != 200:
            print(f"initialize failed: HTTP {init_resp.status_code}")
            print(init_resp.text[:500])
            return 1
        session_id = init_resp.headers.get("mcp-session-id", "")
        init_body = _parse_sse_or_json(init_resp.text)
        server_info = init_body.get("result", {}).get("serverInfo", {})

        sess_headers = dict(headers_base)
        if session_id:
            sess_headers["mcp-session-id"] = session_id

        # 2) initialized notification (no response expected, but transport requires it)
        client.post(
            "/mcp/",
            headers=sess_headers,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )

        # 3) tools/list
        tools_resp = client.post(
            "/mcp/",
            headers=sess_headers,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        )
        if tools_resp.status_code != 200:
            print(f"tools/list failed: HTTP {tools_resp.status_code}")
            print(tools_resp.text[:500])
            return 1
        tools_body = _parse_sse_or_json(tools_resp.text)
        tools = tools_body.get("result", {}).get("tools", []) or []

    print("=" * 72)
    print(f"Server: {server_info.get('name')}  v{server_info.get('version')}")
    print(f"Session: {session_id or '(none)'}")
    print(f"Tools exposed: {len(tools)}")
    print("=" * 72)
    for t in tools:
        name = t.get("name", "?")
        desc = (t.get("description") or "").split("\n")[0].strip()
        if len(desc) > 70:
            desc = desc[:67] + "..."
        print(f"  - {name:42s}  {desc}")
    print("=" * 72)

    # Compare against the docs registry (studio_* tools).
    expected_studio = {
        "studio_generate_image",
        "studio_generate_video",
        "studio_upscale_image",
        "studio_video_enhance",
        "studio_camera_angles",
        "studio_brandshot",
        "studio_casting",
        "studio_digital_twin",
        "studio_ugc_room",
        "studio_convert_to_3d",
        "studio_job_status",
        "studio_credits_balance",
    }
    actual = {t.get("name") for t in tools}
    missing = sorted(expected_studio - actual)
    extra = sorted(actual - expected_studio)
    print()
    if missing:
        print(f"MISSING vs docs ({len(missing)}):")
        for m in missing:
            print(f"  - {m}")
    if extra:
        print(f"EXTRA (in server, not in studio_* docs) ({len(extra)}):")
        for e in extra:
            print(f"  - {e}")
    if not missing and not extra:
        print("OK: server matches the studio_* docs registry.")
        return 0
    return 2 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
