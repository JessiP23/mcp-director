import os

import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-thirty-two-characters!!")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key-value")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("MCP_BASE_URL", "http://testserver")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("DIRECTOR_BASE_URL", "http://mock-director:9420")
os.environ.setdefault("ENVIRONMENT", "development")

import httpx

from src.config import get_settings


@pytest.fixture
def director_base_url():
    return "http://mock-director:9420"


@pytest.fixture
def mock_director(respx_mock, director_base_url):
    respx_mock.get(f"{director_base_url}/health").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    respx_mock.post(f"{director_base_url}/api/runs/").mock(
        return_value=httpx.Response(201, json={"id": "run-1", "status": "queued"})
    )
    respx_mock.post(f"{director_base_url}/api/runs/run-1/cancel").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    respx_mock.get(f"{director_base_url}/api/runs/run-1").mock(
        return_value=httpx.Response(200, json={"id": "run-1", "status": "completed"})
    )
    respx_mock.get(f"{director_base_url}/api/runs/run-99").mock(
        return_value=httpx.Response(
            200,
            json={"id": "run-99", "status": "running", "stage": "script"},
        )
    )
    respx_mock.get(f"{director_base_url}/api/runs/run-1/outputs").mock(
        return_value=httpx.Response(200, json={"script": "# Hello", "assets": []})
    )
    respx_mock.delete(f"{director_base_url}/api/runs/run-1").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    respx_mock.get(f"{director_base_url}/api/runs/").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": "a", "status": "completed", "project_id": "p1"},
                {"id": "b", "status": "running", "project_id": "p1"},
            ],
        )
    )
    respx_mock.get(f"{director_base_url}/api/projects/").mock(
        return_value=httpx.Response(200, json=[{"id": "p1", "name": "Demo"}])
    )
    respx_mock.post(f"{director_base_url}/api/projects/").mock(
        return_value=httpx.Response(201, json={"id": "p-new", "name": "new"})
    )
    respx_mock.post(f"{director_base_url}/api/creative/brief-expand").mock(
        return_value=httpx.Response(
            200,
            json={
                "settings": {"video_model": "quality", "scene_count": 5},
                "production_plan": "Five scenes with cinematic pacing.",
                "request_id": "test-req-id",
            },
        )
    )
    respx_mock.post(f"{director_base_url}/mcp/").mock(
        return_value=httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "structuredContent": {
                        "settings": {"video_model": "quality", "scene_count": 5},
                        "production_plan": "Five scenes with cinematic pacing.",
                    }
                },
            },
        )
    )
    return respx_mock


@pytest.fixture
def valid_token():
    get_settings.cache_clear()
    from src.auth import create_test_token

    return create_test_token(user_id="test-user-123", scopes=["pipeline:write"])


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
