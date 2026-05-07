"""DirectorClient + job tracker tests."""

from __future__ import annotations

import pytest

from src.client import DirectorClient


@pytest.mark.asyncio
async def test_create_run_returns_id(mock_director, director_base_url):
    c = DirectorClient(director_base_url, "tok")
    try:
        r = await c.create_run("p1", "prompt", {})
        assert r.get("id") == "run-1"
    finally:
        await c.aclose()


@pytest.mark.asyncio
async def test_cancel_run_delete(mock_director, director_base_url):
    c = DirectorClient(director_base_url, "tok")
    try:
        r = await c.cancel_run("run-1")
        assert r.get("ok") is True
    finally:
        await c.aclose()


@pytest.mark.asyncio
async def test_list_runs_project_filter_client(mock_director, director_base_url):
    c = DirectorClient(director_base_url, "tok")
    try:
        runs = await c.list_runs(project_id="p1", limit=20)
        assert len(runs) == 2
    finally:
        await c.aclose()


@pytest.mark.asyncio
async def test_rate_limiter_exceed():
    try:
        from fakeredis import aioredis
    except ImportError:
        pytest.skip("fakeredis aioredis")
    from src.rate_limiter import RateLimiter

    redis = aioredis.FakeRedis(decode_responses=True)
    lim = RateLimiter(redis, calls_per_minute=2)
    assert await lim.check_and_increment("u")
    assert await lim.check_and_increment("u")
    assert not await lim.check_and_increment("u")
    await redis.aclose()
