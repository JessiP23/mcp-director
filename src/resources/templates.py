"""Static and dynamic MCP resources + prompt templates."""

from __future__ import annotations

from fastmcp import Context
from fastmcp import FastMCP

from src.client import DirectorClient
from src.config import get_settings


def register_resources(mcp: FastMCP) -> None:
    @mcp.resource("director://docs/pipeline-stages")
    def pipeline_stages_doc() -> str:
        """Documentation for pipeline stages."""
        return """# Director-Cut Pipeline Stages

intake → planning → research → script → storyboard →
assets → audio → edit_assembly → qa → render → package → export

- **intake**: Normalize brief, target platform, brand constraints.
- **planning**: Beat outline, runtime targets, scene count.
- **research**: Reference pulls, tone boards, compliance notes.
- **script**: VO/dialogue, supers, scene numbering.
- **storyboard**: Shot list, framing, blocking, continuity hints.
- **assets**: Image/motion plates, textures, product hero frames.
- **audio**: VO synthesis, music beds, sfx plan.
- **edit_assembly**: Timeline string-out, pacing pass.
- **qa**: Safety, legibility, brand checks.
- **render**: Proxy + finals per scene.
- **package**: Masters, captions, alt ratios.
- **export**: Deliverables bundle + manifests.
"""

    @mcp.resource("director://models/available")
    async def available_models(ctx: Context) -> dict:
        """Video/image model availability (from director-cut settings when reachable)."""
        settings = get_settings()
        token = ""
        try:
            req = ctx.request_context.request if ctx.request_context else None
            if req is not None:
                up = getattr(req.state, "director_bearer_token", None)
                base = getattr(req.state, "bearer_token", "") or ""
                token = (str(up) if up else base) or ""
        except Exception:
            token = ""
        if token:
            try:
                client = DirectorClient(settings.director_base_url, token)
                data = await client.get_settings_public()
                vm = data.get("video_models") or data.get("models", {}).get("video")
                im = data.get("image_models") or data.get("models", {}).get("image")
                if vm or im:
                    return {"video_models": vm or [], "image_models": im or []}
            except Exception:
                pass
        return {
            "video_models": ["fast_turnaround", "balanced", "quality", "cinematic_master"],
            "image_models": ["portrait_v2", "product_shot", "storyboard_sketch"],
            "note": "fallback registry — connect /api/settings for live list",
        }

    @mcp.prompt("director://prompts/product-launch")
    def product_launch_prompt(
        product_name: str,
        product_description: str,
        target_audience: str,
        duration_seconds: int = 60,
    ) -> list:
        """Structured prompt for a product launch video."""
        return [
            {
                "role": "user",
                "content": f"""
Create a {duration_seconds}-second product launch video for:
Product: {product_name}
Description: {product_description}
Audience: {target_audience}

Use director_creative_brief_to_run with style=cinematic and
platform=youtube. Then poll until complete and return the export URL.
""".strip(),
            }
        ]

    @mcp.prompt("director://prompts/social-series")
    def social_series_prompt(topic: str, episode_count: int = 5) -> list:
        """Generate a series of short social videos on a topic."""
        return [
            {
                "role": "user",
                "content": f"""
Use director_creative_batch_variations to create {episode_count}
short-form variations on the topic: "{topic}".
Vary tone and pacing. Return all run_ids and poll for completion.
""".strip(),
            }
        ]

    @mcp.prompt("director://prompts/easy-content-request")
    def easy_content_request(
        brief: str,
        content_type: str = "video",
        style: str = "cinematic",
        platform: str = "youtube",
    ) -> list:
        """Simple starter prompt for non-technical users."""
        return [
            {
                "role": "user",
                "content": f"""
Use director_generate_content for this request:
- brief: {brief}
- content_type: {content_type}
- style: {style}
- platform: {platform}

If a run is queued, poll with director_run_status and return a concise summary with run_id.
""".strip(),
            }
        ]
