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


async def _failure_message_for_run(
    director_client: DirectorClient, run_id: str, run: dict[str, Any], status: str
) -> str:
    """Prefer last_error on GET /runs/:id, then error log; avoids extra /errors round-trip."""
    err = run.get("last_error") or run.get("error") or run.get("message")
    if err and str(err).strip().lower() not in ("", "failed", str(status).lower()):
        return str(err)
    try:
        rows = await director_client.get_run_errors(run_id)
    except DirectorClientError:
        rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        msg = row.get("message")
        if msg and str(msg).strip():
            return str(msg)
    return status


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
        stall_seconds: int = 120,
        report_progress: ProgressCallback = None,
        job_key: str | None = None,
    ) -> dict:
        if job_key is None:
            job_key = await self.submit(run_id, user_id, {"run_id": run_id})
        deadline = time.monotonic() + timeout_seconds
        last_stage = "polling"
        last_stage_change = time.monotonic()
        while time.monotonic() < deadline:
            try:
                run = await director_client.get_run(run_id)
            except DirectorClientError as e:
                await self.mark_failed(job_key, str(e))
                if e.status_code == 404:
                    raise DirectorJobError(
                        f"Run {run_id} disappeared from the backend (404). "
                        "This usually means the director-cut database was reset or "
                        "the run was evicted. Check director-cut Fly volume/db persistence."
                    ) from e
                raise
            status = str(run.get("status") or run.get("state") or "").lower()
            stage = str(run.get("stage") or run.get("current_stage") or last_stage)
            if stage != last_stage:
                last_stage = stage
                last_stage_change = time.monotonic()
            elapsed = timeout_seconds - max(0, deadline - time.monotonic())
            stall_elapsed = time.monotonic() - last_stage_change
            if report_progress:
                await report_progress(
                    {
                        "stage": stage,
                        "elapsed_seconds": round(elapsed, 2),
                        "estimated_remaining": max(0, round(deadline - time.monotonic(), 2)),
                        "stalled_seconds": round(stall_elapsed, 0) if stall_elapsed > 30 else 0,
                    }
                )
            if status in ("completed", "success", "succeeded", "done"):
                outputs = await director_client.get_run_outputs(run_id)
                await self.mark_complete(job_key, outputs)
                return outputs
            if status in ("failed", "error", "cancelled", "canceled"):
                err = await _failure_message_for_run(
                    director_client, run_id, run, status
                )
                await self.mark_failed(job_key, str(err))
                raise DirectorJobError(str(err))
            # Detect stall: stage hasn't changed in stall_seconds
            if stall_elapsed > stall_seconds:
                msg = (
                    f"Run {run_id} has been in stage '{stage}' for "
                    f"{round(stall_elapsed)}s without progress. "
                    "The director-cut render process may have stalled or crashed."
                )
                await self.mark_failed(job_key, msg)
                raise DirectorJobError(msg)
            await asyncio.sleep(poll_interval)

        await self.mark_failed(job_key, "timeout")
        raise DirectorTimeoutError(f"run {run_id} did not complete in {timeout_seconds}s")
