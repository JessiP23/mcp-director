"""HTTP-level 401 + WWW-Authenticate gate on /mcp/* — required for MCP-spec auth flow.

Without this, missing/invalid bearer surfaces as a JSON-RPC error inside a 200,
and Claude.ai never re-initiates OAuth. See server.py::_mcp_bearer_gate.
"""

from fastapi.testclient import TestClient

from src.auth import create_test_token
from src.server import root_app


def test_mcp_without_bearer_returns_401_with_challenge():
    with TestClient(root_app) as client:
        r = client.post("/mcp/", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code == 401
    challenge = r.headers.get("www-authenticate", "")
    assert challenge.startswith("Bearer ")
    assert "resource_metadata=" in challenge
    assert "/.well-known/oauth-protected-resource" in challenge


def test_mcp_with_invalid_bearer_returns_401_with_invalid_token_error():
    with TestClient(root_app) as client:
        r = client.post(
            "/mcp/",
            headers={"Authorization": "Bearer not-a-real-jwt"},
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        )
    assert r.status_code == 401
    challenge = r.headers.get("www-authenticate", "")
    assert 'error="invalid_token"' in challenge


def test_mcp_with_valid_bearer_passes_gate():
    """Valid bearer is forwarded to the mounted MCP app (no 401)."""
    token = create_test_token()
    with TestClient(root_app) as client:
        r = client.post(
            "/mcp/",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json, text/event-stream",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"},
            }},
        )
    # Past the bearer gate — anything other than 401 means the gate passed.
    assert r.status_code != 401, (
        f"valid bearer should not be rejected by gate: {r.status_code} {r.text[:200]}"
    )


def test_mcp_options_preflight_bypasses_gate():
    with TestClient(root_app) as client:
        r = client.options(
            "/mcp/",
            headers={
                "Origin": "https://claude.ai",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
    assert r.status_code != 401
