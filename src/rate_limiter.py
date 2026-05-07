"""Sliding-window rate limiting per user (Redis sorted sets)."""

from __future__ import annotations

import time
import uuid

from redis.asyncio import Redis


class RateLimiter:
    def __init__(self, redis: Redis, calls_per_minute: int = 60) -> None:
        self._redis = redis
        self._limit = max(1, calls_per_minute)

    async def check_and_increment(self, user_id: str) -> bool:
        key = f"rl:{user_id}"
        now = time.time()
        window_start = now - 60.0
        pipe = self._redis.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zcard(key)
        rem: list = await pipe.execute()
        count = int(rem[1])
        if count >= self._limit:
            return False
        member = f"{now}:{uuid.uuid4().hex}"
        pipe = self._redis.pipeline()
        pipe.zadd(key, {member: now})
        pipe.expire(key, 120)
        await pipe.execute()
        return True

    async def remaining(self, user_id: str) -> int:
        key = f"rl:{user_id}"
        now = time.time()
        window_start = now - 60.0
        await self._redis.zremrangebyscore(key, 0, window_start)
        count = int(await self._redis.zcard(key))
        return max(0, self._limit - count)
