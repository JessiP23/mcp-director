"""Analytics and cost insight tools."""

from __future__ import annotations

from statistics import mean

from fastmcp import Context
from fastmcp import FastMCP

from src.tools.pipeline import _user_client


def register(mcp: FastMCP) -> None:
    @mcp.tool(name="director_insight_run_cost")
    async def estimate_cost(
        ctx: Context,
        project_id: str | None = None,
        run_id: str | None = None,
    ) -> dict:
        """
        Estimate or report actual API costs for a run or project.
        Returns llm_cost_usd, render_cost_usd, total_usd, and model_breakdown.
        """
        _, client = _user_client(ctx)
        runs = []
        if run_id:
            runs = [await client.get_run(run_id)]
        elif project_id:
            runs = await client.list_runs(project_id=project_id, limit=100)
        else:
            runs = await client.list_runs(limit=50)
        llm = 0.0
        render = 0.0
        breakdown: dict[str, float] = {}
        for r in runs:
            usage = r.get("usage") or r.get("cost") or {}
            if isinstance(usage, dict):
                llm += float(usage.get("llm_usd", 0) or 0)
                render += float(usage.get("render_usd", 0) or 0)
                for m, v in usage.get("models", {}).items():
                    breakdown[str(m)] = breakdown.get(str(m), 0.0) + float(v)
        if not runs:
            return {
                "llm_cost_usd": 0.0,
                "render_cost_usd": 0.0,
                "total_usd": 0.0,
                "model_breakdown": {},
                "note": "no runs matched — connect director-cut cost telemetry for precise totals",
            }
        return {
            "llm_cost_usd": round(llm, 4),
            "render_cost_usd": round(render, 4),
            "total_usd": round(llm + render, 4),
            "model_breakdown": {k: round(v, 4) for k, v in breakdown.items()},
            "runs_considered": len(runs),
        }

    @mcp.tool(name="director_insight_pipeline_analytics")
    async def pipeline_analytics(ctx: Context, project_id: str) -> dict:
        """
        Return analytics for a project: avg run time per stage, success rate,
        most-used models, total runs, total render minutes.
        """
        _, client = _user_client(ctx)
        runs = await client.list_runs(project_id=project_id, limit=200)
        if not runs:
            return {"project_id": project_id, "total_runs": 0}
        successes = sum(
            1
            for r in runs
            if str(r.get("status") or r.get("state") or "").lower()
            in ("completed", "success", "succeeded", "done")
        )
        durations = [
            float(r.get("duration_seconds") or r.get("duration") or 0)
            for r in runs
            if float(r.get("duration_seconds") or r.get("duration") or 0) > 0
        ]
        models: dict[str, int] = {}
        for r in runs:
            m = str(r.get("video_model") or r.get("model") or "unknown")
            models[m] = models.get(m, 0) + 1
        top_model = max(models, key=lambda k: models[k])
        return {
            "project_id": project_id,
            "total_runs": len(runs),
            "success_rate": round(successes / len(runs), 4),
            "avg_duration_seconds": round(mean(durations), 2) if durations else 0.0,
            "most_used_model": top_model,
            "model_counts": models,
            "total_render_minutes": round(sum(durations) / 60.0, 2),
        }

    @mcp.tool(name="director_insight_model_recommendations")
    async def model_recommendations(
        ctx: Context,
        use_case: str,
        budget_usd: float | None = None,
    ) -> list:
        """
        Recommend optimal video/image models for a given use case and optional budget.
        Use cases: ugc, cinematic, product, social, documentary.
        """
        uc = use_case.lower()
        recs: list[dict] = []
        if uc == "ugc":
            recs = [
                {"model": "fast_social", "role": "primary", "reason": "Short hooks, fast iteration"},
                {"model": "face_safe", "role": "b_roll", "reason": "People-forward framing"},
            ]
        elif uc == "cinematic":
            recs = [
                {"model": "cinematic_master", "role": "primary", "reason": "Lighting + camera language"},
                {"model": "hdr_color", "role": "finishing", "reason": "Grade-friendly outputs"},
            ]
        elif uc == "product":
            recs = [
                {"model": "packshot_clean", "role": "primary", "reason": "Controlled surfaces"},
                {"model": "macro_detail", "role": "inserts", "reason": "Texture emphasis"},
            ]
        elif uc in ("social", "short"):
            recs = [
                {"model": "vertical_9_16", "role": "primary", "reason": "Platform-native crops"},
                {"model": "caption_safe", "role": "graphics", "reason": "Readable supers"},
            ]
        else:
            recs = [
                {"model": "balanced_doc", "role": "primary", "reason": "Interview + b-roll mix"},
            ]
        if budget_usd is not None and budget_usd < 5:
            recs.append(
                {
                    "model": "economy_mode",
                    "role": "overflow",
                    "reason": "Clamp cost with shorter generations",
                }
            )
        return recs
