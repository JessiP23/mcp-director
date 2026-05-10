"""Creative, high-level director tools."""

from __future__ import annotations

import asyncio
import itertools
import json
import re
import uuid

import structlog
from fastmcp import Context
from fastmcp import FastMCP
from redis.asyncio import Redis

from src.client import DirectorClient, DirectorClientError
from src.config import get_settings
from src.job_tracker import JobTracker
from src.tools.pipeline import _user_client

log = structlog.get_logger(__name__)


def _parse_variation_dims(variation_dimensions: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for item in variation_dimensions:
        if ":" not in item:
            continue
        key, rest = item.split(":", 1)
        vals = [p.strip() for p in rest.split(",") if p.strip()]
        if vals:
            out[key.strip()] = vals
    return out


def _slug_title(brief: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", brief[:48])
    return "-".join(w.lower() for w in words[:6]) or "production"


def _normalize_content_type(content_type: str) -> str:
    c = content_type.strip().lower()
    aliases = {
        "video": "video",
        "videos": "video",
        "clip": "video",
        "clips": "video",
        "image": "image",
        "images": "image",
        "thumbnail": "image",
        "thumbnails": "image",
        "poster": "image",
    }
    if c not in aliases:
        raise ValueError("content_type must be one of: video, image")
    return aliases[c]


async def _expand_brief_with_llm(
    client: DirectorClient,
    brief: str,
    style: str,
    duration_target_seconds: int,
    platform: str,
) -> tuple[dict, str]:
    try:
        result = await client.post_mcp_jsonrpc(
            "tools/call",
            params={
                "name": "director_service_llm",
                "arguments": {
                    "task": "brief_to_settings",
                    "brief": brief,
                    "style": style,
                    "duration_target_seconds": duration_target_seconds,
                    "platform": platform,
                },
            },
        )
        if isinstance(result, dict) and result.get("structuredContent"):
            sc = result["structuredContent"]
            if isinstance(sc, dict):
                settings = sc.get("settings", sc)
                plan = sc.get("production_plan") or sc.get("summary") or ""
                return settings if isinstance(settings, dict) else {}, str(plan)
        if isinstance(result, dict) and "settings" in result:
            return result["settings"], str(result.get("production_plan", ""))
    except DirectorClientError as e:
        log.info("brief_llm_fallback", reason=str(e))
    scenes = max(3, min(18, duration_target_seconds // 6))
    model = "balanced"
    if style.lower() in ("cinematic", "documentary"):
        model = "quality"
    if duration_target_seconds <= 30:
        model = "fast_turnaround"
    settings = {
        "video_model": model,
        "scene_count": scenes,
        "style": style,
        "platform": platform,
        "brief_expansion": brief[:800],
    }
    plan = (
        f"{scenes} scenes, {style} treatment, optimized for {platform} "
        f"(~{duration_target_seconds}s target)."
    )
    return settings, plan


def register(mcp: FastMCP) -> None:
    @mcp.tool(name="director_generate_content")
    async def generate_content(
        ctx: Context,
        brief: str,
        content_type: str = "video",
        style: str = "cinematic",
        platform: str = "youtube",
        duration_target_seconds: int = 60,
        project_name: str = "",
        wait_for_completion: bool = False,
        timeout_seconds: int = 900,
    ) -> dict:
        """
        Beginner-friendly content generation entrypoint.

        Creates (or reuses) a project, applies sensible defaults, starts a run,
        and optionally waits for completion. Use this when users don't know the
        lower-level tool set yet.
        """
        user_id, client = _user_client(ctx)
        normalized = _normalize_content_type(content_type)
        run_duration = max(8, duration_target_seconds)
        settings, plan = await _expand_brief_with_llm(
            client,
            brief,
            style,
            run_duration,
            platform,
        )
        if normalized == "image":
            # Keep image requests fast and deterministic by default.
            settings.update(
                {
                    "target_output": "image",
                    "scene_count": 1,
                    "target_duration_seconds": 8,
                }
            )
            run_duration = 8
        else:
            settings["target_duration_seconds"] = run_duration

        name = project_name.strip() or f"{_slug_title(brief)}-{normalized}"
        proj = await client.create_project(name=name[:80], description=brief[:500])
        project_id = str(proj.get("id") or proj.get("project_id") or "")
        if not project_id:
            raise RuntimeError("could not create a project for content generation")

        run = await client.create_run(project_id, brief, settings)
        run_id = str(run.get("id") or run.get("run_id") or "")
        if not run_id:
            raise RuntimeError("run creation failed")

        response = {
            "run_id": run_id,
            "project_id": project_id,
            "content_type": normalized,
            "production_plan": plan,
            "status": str(run.get("status") or "queued"),
            "next_step": "Poll with director_run_status or set wait_for_completion=true.",
        }
        if not wait_for_completion:
            return response

        redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
        try:
            tracker = JobTracker(redis)
            outputs = await tracker.poll_until_done(
                run_id,
                user_id,
                client,
                timeout_seconds=max(60, timeout_seconds),
                poll_interval=5.0,
            )
            response["status"] = "completed"
            response["outputs"] = outputs
            return response
        finally:
            await redis.aclose()

    @mcp.tool(name="director_creative_brief_to_run")
    async def brief_to_run(
        ctx: Context,
        brief: str,
        style: str = "cinematic",
        duration_target_seconds: int = 60,
        platform: str = "youtube",
        auto_create_project: bool = True,
    ) -> dict:
        """
        Transform a high-level creative brief into a complete pipeline run.
        Automatically selects optimal video_model, infers scene count from
        duration target, and names the project from the brief.
        Returns run_id and a human-readable production_plan summary.

        Example brief: "A product launch video for noise-cancelling headphones
        targeting remote workers, emphasizing focus and deep work."
        """
        user_id, client = _user_client(ctx)
        settings, plan = await _expand_brief_with_llm(
            client, brief, style, duration_target_seconds, platform
        )
        project_id: str | None = None
        if auto_create_project:
            name = _slug_title(brief)
            proj = await client.create_project(
                name=f"{name}-{platform}",
                description=brief[:500],
            )
            project_id = str(proj.get("id") or proj.get("project_id") or "")
        else:
            projects = await client.list_projects()
            if projects:
                project_id = str(projects[0].get("id") or projects[0].get("project_id"))
        if not project_id:
            raise RuntimeError("project_id required — enable auto_create_project or create a project")
        merged = {**settings, "target_duration_seconds": duration_target_seconds}
        run = await client.create_run(project_id, brief, merged)
        run_id = str(run.get("id") or run.get("run_id") or "")
        return {
            "run_id": run_id,
            "project_id": project_id,
            "production_plan": plan,
            "estimated_duration_minutes": max(2, duration_target_seconds // 60 + 1),
            "settings_applied": merged,
        }

    @mcp.tool(name="director_creative_batch_variations")
    async def batch_variations(
        ctx: Context,
        base_prompt: str,
        variation_dimensions: list[str],
        project_id: str,
        max_concurrent: int = 3,
    ) -> dict:
        """
        Generate N variations of a video concept in parallel by varying
        specified dimensions (e.g. ["tone:serious,playful", "pacing:slow,fast"]).
        Submits up to max_concurrent runs simultaneously.
        Returns {batch_id, run_ids, variation_matrix}.
        """
        user_id, client = _user_client(ctx)
        dims = _parse_variation_dims(variation_dimensions)
        if not dims:
            raise ValueError("variation_dimensions must include key:value1,value2 entries")
        keys = list(dims.keys())
        value_lists = [dims[k] for k in keys]
        combos = list(itertools.product(*value_lists))

        sem = asyncio.Semaphore(max(1, max_concurrent))
        matrix: list[dict] = []

        async def _one(combo: tuple[str, ...]) -> dict:
            variant = {keys[i]: combo[i] for i in range(len(keys))}
            prompt = f"{base_prompt}\n\nVariants: {json.dumps(variant)}"
            async with sem:
                r = await client.create_run(project_id, prompt, {"variations": variant})
                rid = str(r.get("id") or r.get("run_id") or "")
                return {"run_id": rid, **variant}

        matrix = await asyncio.gather(*(_one(c) for c in combos))
        run_ids = [str(m.get("run_id", "")) for m in matrix]

        batch_id = str(uuid.uuid4())
        settings = get_settings()
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        try:
            await redis.setex(
                f"batch:{user_id}:{batch_id}",
                86400,
                json.dumps({"run_ids": run_ids, "matrix": matrix}),
            )
        finally:
            await redis.aclose()

        return {"batch_id": batch_id, "run_ids": run_ids, "variation_matrix": matrix}

    @mcp.tool(name="director_creative_remix")
    async def remix_run(
        ctx: Context,
        source_run_id: str,
        remix_instructions: str,
        stages_to_rerun: list[str] | None = None,
    ) -> dict:
        """
        Take a completed run and remix it with new instructions, re-running
        only the specified stages while preserving earlier stage outputs.
        Useful for: "keep the script but change the visual style to noir."
        Returns new run_id.
        """
        _, client = _user_client(ctx)
        stages_to_rerun = stages_to_rerun or ["script", "storyboard", "render"]
        source = await client.get_run(source_run_id)
        outputs = await client.get_run_outputs(source_run_id)
        project_id = str(source.get("project_id") or outputs.get("project_id") or "")
        if not project_id:
            raise RuntimeError("could not resolve project_id for source run")
        base_prompt = str(source.get("prompt") or outputs.get("prompt") or "")
        merged_prompt = f"{base_prompt}\n\nRemix: {remix_instructions}"
        settings = {
            "remix_of": source_run_id,
            "stages_to_rerun": stages_to_rerun,
            "seed_checkpoint": outputs,
        }
        run = await client.create_run(project_id, merged_prompt, settings)
        return {
            "new_run_id": str(run.get("id") or run.get("run_id") or ""),
            "source_run_id": source_run_id,
            "stages_to_rerun": stages_to_rerun,
        }

    @mcp.tool(name="director_creative_storyboard_preview")
    async def storyboard_preview(ctx: Context, run_id: str) -> dict:
        """Return structured storyboard / scene data when present in run outputs."""
        _, client = _user_client(ctx)
        outputs = await client.get_run_outputs(run_id)
        scenes = outputs.get("storyboard") or outputs.get("scenes") or outputs.get("shots")
        if isinstance(scenes, str):
            try:
                scenes = json.loads(scenes)
            except json.JSONDecodeError:
                scenes = [{"description": scenes}]
        if not scenes:
            script = outputs.get("script")
            scenes = [{"shot_description": "n/a", "dialogue": "", "notes": str(script)[:400]}]
        return {"run_id": run_id, "scenes": scenes}

    @mcp.tool(name="director_creative_script_extract")
    async def script_extract(ctx: Context, run_id: str, format: str = "markdown") -> str:
        """Extract the final script from a run in markdown, fountain, plain, or json."""
        _, client = _user_client(ctx)
        outputs = await client.get_run_outputs(run_id)
        script = outputs.get("script") or outputs.get("final_script") or ""
        if format == "json":
            return json.dumps({"script": script}, indent=2)
        if format == "fountain":
            text = str(script)
            if not text.startswith("Title:"):
                return f"Title: Extracted\n\n{text}"
            return text
        if format == "plain":
            return re.sub(r"[#*_`]", "", str(script))
        return str(script)

    @mcp.tool(name="director_creative_suggest_improvements")
    async def suggest_improvements(
        ctx: Context,
        run_id: str,
        aspect: str = "all",
    ) -> dict:
        """Analyze outputs via director LLM service when available."""
        _, client = _user_client(ctx)
        outputs = await client.get_run_outputs(run_id)
        try:
            result = await client.post_mcp_jsonrpc(
                "tools/call",
                params={
                    "name": "director_service_llm",
                    "arguments": {
                        "task": "suggest_improvements",
                        "aspect": aspect,
                        "outputs": outputs,
                    },
                },
            )
            if isinstance(result, dict) and result.get("structuredContent"):
                return {"run_id": run_id, "suggestions": result["structuredContent"]}
            if isinstance(result, dict):
                return {"run_id": run_id, "suggestions": result}
        except DirectorClientError:
            pass
        return {
            "run_id": run_id,
            "suggestions": [
                {
                    "severity": "info",
                    "area": aspect,
                    "message": "LLM analyzer unavailable; review pacing and clarity manually.",
                    "suggested_prompt_delta": "Tighten CTAs and reduce VO density in the final act.",
                }
            ],
        }
