"""JobTracker Redis behavior."""

from __future__ import annotations

import httpx
import pytest

from src.client import DirectorClient
from src.job_tracker import JobTracker


@pytest.mark.asyncio
async def test_poll_until_done_success(mock_director, director_base_url):
    try:
        from fakeredis import aioredis
    except ImportError:
        pytest.skip("fakeredis aioredis missing")
    redis = aioredis.FakeRedis(decode_responses=True)
    tracker = JobTracker(redis)
    client = DirectorClient(director_base_url, "tok")
    try:
        out = await tracker.poll_until_done(
            "run-1",
            "user-1",
            client,
            timeout_seconds=30,
            poll_interval=0.01,
        )
        assert "script" in out
    finally:
        await redis.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_poll_until_done_failed_uses_last_error_from_get_run(
    mock_director, director_base_url, respx_mock
):
    try:
        from fakeredis import aioredis
    except ImportError:
        pytest.skip("fakeredis aioredis missing")
    respx_mock.get(f"{director_base_url}/api/runs/run-fail").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "run-fail",
                "status": "failed",
                "current_stage": "planning",
                "last_error": "Stage planning timed out (300 s)",
            },
        )
    )
    redis = aioredis.FakeRedis(decode_responses=True)
    tracker = JobTracker(redis)
    client = DirectorClient(director_base_url, "tok")
    try:
        from src.job_tracker import DirectorJobError

        with pytest.raises(DirectorJobError, match="planning timed out"):
            await tracker.poll_until_done(
                "run-fail",
                "user-1",
                client,
                timeout_seconds=30,
                poll_interval=0.01,
            )
    finally:
        await redis.aclose()
        await client.aclose()
