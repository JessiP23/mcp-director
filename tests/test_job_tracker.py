"""JobTracker Redis behavior."""

from __future__ import annotations

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
