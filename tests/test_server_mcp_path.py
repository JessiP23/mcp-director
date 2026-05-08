"""Bare /mcp must reach the mounted MCP app (no 404 from Mount mismatch)."""

from fastapi.testclient import TestClient

from src.server import root_app


def test_bare_mcp_path_reaches_mount_not_404():
    with TestClient(root_app) as client:
        r = client.get("/mcp", follow_redirects=False)
    assert r.status_code != 404, "bare /mcp should normalize to MCP mount, not fall through"
    assert r.status_code != 307
