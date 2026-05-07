"""Redis-backed job tracking and polling for long-running director runs."""

from __future__ import annotations

# mypy: disable-error-code="misc"

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

from redis.asyncio import Redis

from src.client import DirectorClient, DirectorClientError

ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]] | None


class DirectorJobError(RuntimeError):
    pass


class DirectorTimeoutError(TimeoutError):
    pass


class JobTracker:
    JOB_TTL = 86400

    def __init__(self, redis: Redis) -> None:
        self._r = redis

    async def submit(self, run_id: str, user_id: str, metadata: dict) -> str:
        job_key = f"job:{user_id}:{run_id}"
        payload = {
            "status": "running",
            "created_at": str(time.time()),
            "metadata": json.dumps(metadata),
        }
        await self._r.hset(job_key, mapping=payload)
        await self._r.expire(job_key, self.JOB_TTL)
        return job_key

    async def get_status(self, job_key: str) -> dict[str, Any]:
        data = await self._r.hgetall(job_key)
        if not data:
            return {}
        out = dict(data)
        if "metadata" in out:
            try:
                out["metadata"] = json.loads(out["metadata"])
            except json.JSONDecodeError:
                pass
        return out

    async def mark_complete(self, job_key: str, outputs: dict) -> None:
        await self._r.hset(
            job_key,
            mapping={
                "status": "completed",
                "completed_at": str(time.time()),
                "outputs": json.dumps(outputs),
            },
        )
        await self._r.expire(job_key, self.JOB_TTL)

    async def mark_failed(self, job_key: str, error: str) -> None:
        await self._r.hset(
            job_key,
            mapping={
                "status": "failed",
                "completed_at": str(time.time()),
                "error": error[:4000],
            },
        )
        await self._r.expire(job_key, self.JOB_TTL)

    async def poll_until_done(
        self,
        run_id: str,
        user_id: str,
        director_client: DirectorClient,
        *,
        timeout_seconds: int = 600,
        poll_interval: float = 5.0,
        report_progress: ProgressCallback = None,
        job_key: str | None = None,
    ) -> dict:
        if job_key is None:
            job_key = await self.submit(run_id, user_id, {"run_id": run_id})
        deadline = time.monotonic() + timeout_seconds
        last_stage = "polling"
        while time.monotonic() < deadline:
            try:
                run = await director_client.get_run(run_id)
            except DirectorClientError as e:
                await self.mark_failed(job_key, str(e))
                raise
            status = str(run.get("status") or run.get("state") or "").lower()
            stage = str(run.get("stage") or run.get("current_stage") or last_stage)
            last_stage = stage
            elapsed = timeout_seconds - max(0, deadline - time.monotonic())
            if report_progress:
                await report_progress(
                    {
                        "stage": stage,
                        "elapsed_seconds": round(elapsed, 2),
                        "estimated_remaining": max(0, round(deadline - time.monotonic(), 2)),
                    }
                )
            if status in ("completed", "success", "succeeded", "done"):
                outputs = await director_client.get_run_outputs(run_id)
                await self.mark_complete(job_key, outputs)
                return outputs
            if status in ("failed", "error", "cancelled", "canceled"):
                err = run.get("error") or run.get("message") or status
                await self.mark_failed(job_key, str(err))
                raise DirectorJobError(str(err))
            await asyncio.sleep(poll_interval)

        await self.mark_failed(job_key, "timeout")
        raise DirectorTimeoutError(f"run {run_id} did not complete in {timeout_seconds}s")
