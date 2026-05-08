"""Pipeline and project tools (director_run_*, director_project_*)."""

from __future__ import annotations

from typing import Any

import structlog
from fastmcp import Context
from fastmcp import FastMCP

from src.client import DirectorClient
from src.config import get_settings
from src.job_tracker import JobTracker

log = structlog.get_logger(__name__)


def _user_client(ctx: Context) -> tuple[str, DirectorClient]:
    rc = ctx.request_context
    if rc is None or rc.request is None:
        raise RuntimeError("missing request context")
    mcp_token = getattr(rc.request.state, "bearer_token", None)
    director_token = getattr(rc.request.state, "director_bearer_token", None)
    user_id = getattr(rc.request.state, "user_id", None)
    if not mcp_token or not user_id:
        raise RuntimeError("not authenticated")
    bearer = str(director_token) if director_token else str(mcp_token)
    return str(user_id), DirectorClient(get_settings().director_base_url, bearer)


def register(mcp: FastMCP) -> None:
    @mcp.tool(name="director_run_create")
    async def create_run(
        ctx: Context,
        project_id: str,
        prompt: str,
        settings: dict[str, Any] | None = None,
        wait_for_completion: bool = False,
        timeout_seconds: int = 600,
    ) -> dict:
        """
        Start a new director-cut AI video pipeline run.
        If wait_for_completion=True, polls until done and returns full outputs.
        If False, returns immediately with run_id for async polling.
        """
        user_id, client = _user_client(ctx)
        created = await client.create_run(project_id, prompt, settings or {})
        run_id = str(created.get("id") or created.get("run_id") or "")
        if not run_id:
            return created
        if not wait_for_completion:
            return {"run_id": run_id, **{k: v for k, v in created.items() if k != "id"}}

        settings_obj = get_settings()
        from redis.asyncio import Redis

        redis = Redis.from_url(settings_obj.redis_url, decode_responses=True)
        try:
            tracker = JobTracker(redis)

            async def _progress(info: dict) -> None:
                msg = f"{info.get('stage')} ({info.get('elapsed_seconds')}s)"
                try:
                    await ctx.report_progress(
                        min(95.0, float(info.get("elapsed_seconds", 0))),
                        float(timeout_seconds),
                        msg,
                    )
                except Exception:
                    pass

            outputs = await tracker.poll_until_done(
                run_id,
                user_id,
                client,
                timeout_seconds=timeout_seconds,
                poll_interval=5.0,
                report_progress=_progress,
            )
            return {"run_id": run_id, "outputs": outputs, "status": "completed"}
        finally:
            await redis.aclose()

    @mcp.tool(name="director_run_status")
    async def get_run_status(ctx: Context, run_id: str) -> dict:
        """Get the current status, stage, and progress of a pipeline run."""
        _, client = _user_client(ctx)
        return await client.get_run(run_id)

    @mcp.tool(name="director_run_outputs")
    async def get_run_outputs(ctx: Context, run_id: str) -> dict:
        """
        Retrieve all outputs from a completed run including script, storyboard,
        asset URLs, render URLs, and export paths.
        """
        _, client = _user_client(ctx)
        return await client.get_run_outputs(run_id)

    @mcp.tool(name="director_run_cancel")
    async def cancel_run(ctx: Context, run_id: str) -> dict:
        """Cancel an in-progress pipeline run."""
        _, client = _user_client(ctx)
        return await client.cancel_run(run_id)

    @mcp.tool(name="director_run_list")
    async def list_runs(
        ctx: Context,
        project_id: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list:
        """List pipeline runs, optionally filtered by project or status."""
        _, client = _user_client(ctx)
        runs = await client.list_runs(project_id=project_id, limit=limit)
        if not status:
            return runs
        st = status.lower()
        out = []
        for r in runs:
            rs = str(r.get("status") or r.get("state") or "").lower()
            if rs == st:
                out.append(r)
        return out

    @mcp.tool(name="director_project_create")
    async def create_project(ctx: Context, name: str, description: str = "") -> dict:
        """Create a new project to organize pipeline runs."""
        _, client = _user_client(ctx)
        return await client.create_project(name, description)

    @mcp.tool(name="director_project_list")
    async def list_projects(ctx: Context) -> list:
        """List all projects for the authenticated user."""
        _, client = _user_client(ctx)
        return await client.list_projects()
