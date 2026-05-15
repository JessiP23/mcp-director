"""WM Studio creative tools — 12 documented `studio_*` MCP handlers.

Each tool forwards to the WM Studio Next.js API at /api/creative-studio/*
or /api/jobs/* using the user's upstream Supabase access token.

All tools are synchronous from the MCP client's perspective: WM Studio's
fal.ai integration runs as `fal.subscribe(...)` inline, so a successful
response already contains the generated asset URL. For models that route
through the WM Studio job queue (when `CREATIVE_STUDIO_QUEUE_ENABLED=true`),
the response is `{ jobId, status: "processing" }` and the caller polls via
`studio_job_status`.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_request

from src.config import get_settings
from src.wmstudio_client import WMStudioClient, WMStudioClientError, get_user_wmstudio_client

log = structlog.get_logger(__name__)


def _client() -> WMStudioClient:
    request = get_http_request()
    settings = get_settings()
    return get_user_wmstudio_client(request.state, settings.wmstudio_api_url)


def _safe_call(label: str, fn):  # type: ignore[no-untyped-def]
    """Wrap upstream errors into structured tool responses (don't crash the session)."""
    async def runner(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return await fn(*args, **kwargs)
        except WMStudioClientError as e:
            log.warning(
                "studio_tool_upstream_error",
                tool=label,
                status=e.status_code,
                message=str(e.message)[:200],
            )
            return {
                "ok": False,
                "error": "upstream_error",
                "status": e.status_code,
                "message": str(e.message),
                "details": e.payload,
            }

    return runner


def _drop_none(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


def register(mcp: FastMCP) -> None:
    # ---------- Image generation ----------

    @mcp.tool(name="studio_generate_image")
    async def studio_generate_image(
        prompt: str,
        model: str = "fal-ai/flux/dev",
        aspect_ratio: str | None = None,
        image_url: str | None = None,
        negative_prompt: str | None = None,
        num_images: int | None = None,
        seed: int | None = None,
    ) -> dict:
        """Generate an image with WM Studio via fal.ai.

        Defaults to flux/dev. Pass `image_url` for img2img variants.
        Returns `{ imageUrl, images, generationId, requestId, creditsCharged }`
        on sync completion, or `{ jobId, status }` if the request is queued.
        """
        client = _client()
        try:
            payload = _drop_none({
                "prompt": prompt,
                "model": model,
                "aspect_ratio": aspect_ratio,
                "imageUrl": image_url,
                "negative_prompt": negative_prompt,
                "num_images": num_images,
                "seed": seed,
            })
            return await client.generate_image(payload)
        finally:
            await client.aclose()

    @mcp.tool(name="studio_upscale_image")
    async def studio_upscale_image(
        image_url: str,
        upscale_factor: int = 2,
        model: str = "fal-ai/topaz/upscale/image",
        topaz_model: str = "Standard V2",
        face_enhancement: bool = True,
        output_format: str = "jpeg",
    ) -> dict:
        """Upscale an existing image with Topaz.

        - `upscale_factor`: 1–4 (2 or 4 are the most useful).
        - `topaz_model`: one of `"Low Resolution V2"`, `"Standard V2"`,
          `"High Fidelity V2"`, `"Text Refine"`, `"CGI"`. Defaults to
          `"Standard V2"`. Note: this is the Topaz **preset**, distinct
          from the fal app id passed in `model`.
        - `face_enhancement`: enable Topaz's face refinement pass.
        - `output_format`: `"jpeg"` or `"png"`.
        """
        client = _client()
        try:
            payload = {
                "model": model,
                "imageUrl": image_url,
                "upscale_factor": upscale_factor,
                "topazModel": topaz_model,
                "face_enhancement": face_enhancement,
                "output_format": output_format,
                "prompt": "",  # required by route shape; ignored by upscale handlers
            }
            return await client.generate_image(payload)
        finally:
            await client.aclose()

    @mcp.tool(name="studio_camera_angles")
    async def studio_camera_angles(
        prompt: str,
        camera: str,
        image_url: str | None = None,
        model: str = "fal-ai/flux/dev",
        aspect_ratio: str | None = None,
    ) -> dict:
        """Generate an image with an explicit cinematic camera angle.

        `camera` is a free-form descriptor (e.g. "low angle", "dutch tilt",
        "over-the-shoulder"). The WM Studio prompt-engineer composes the
        final prompt downstream.
        """
        client = _client()
        try:
            payload = _drop_none({
                "prompt": prompt,
                "model": model,
                "aspect_ratio": aspect_ratio,
                "imageUrl": image_url,
                "metadata": {"toolId": "camera_angles", "camera": camera},
            })
            return await client.generate_image(payload)
        finally:
            await client.aclose()

    @mcp.tool(name="studio_brandshot")
    async def studio_brandshot(
        prompt: str,
        product_image_url: str | None = None,
        brand_palette: list[str] | None = None,
        model: str = "fal-ai/flux/dev",
        aspect_ratio: str | None = None,
    ) -> dict:
        """Brand-consistent product/marketing shot. Pass the product image and
        an optional brand color palette (hex strings)."""
        client = _client()
        try:
            metadata: dict[str, Any] = {"toolId": "brandshot"}
            if brand_palette:
                metadata["brandPalette"] = brand_palette
            payload = _drop_none({
                "prompt": prompt,
                "model": model,
                "aspect_ratio": aspect_ratio,
                "imageUrl": product_image_url,
                "metadata": metadata,
            })
            return await client.generate_image(payload)
        finally:
            await client.aclose()

    @mcp.tool(name="studio_casting")
    async def studio_casting(
        character_name: str,
        prompt: str,
        character_profile: dict[str, Any] | None = None,
        model: str = "fal-ai/flux/dev",
        aspect_ratio: str | None = None,
    ) -> dict:
        """Generate a character casting shot.

        `character_profile` accepts WM Studio's casting schema keys:
        `characterType, genderIdentity, raceEthnicity, eyeColor, heightCm,
        weightKg, bodyType, hairStyle, hairTexture, hairColor, facialHair,
        outfitStyle, outfitDetails, cinematicGenre, characterArchetype,
        eraSetting`. All optional; the route sanitizes unknown keys.
        """
        client = _client()
        try:
            metadata: dict[str, Any] = {
                "toolId": "casting",
                "characterName": character_name,
            }
            if character_profile:
                metadata["characterProfile"] = character_profile
            payload = _drop_none({
                "prompt": prompt,
                "userPrompt": character_name,
                "model": model,
                "aspect_ratio": aspect_ratio,
                "metadata": metadata,
            })
            return await client.generate_image(payload)
        finally:
            await client.aclose()

    @mcp.tool(name="studio_digital_twin")
    async def studio_digital_twin(
        prompt: str,
        digital_twin_profile_id: str | None = None,
        enhancement_preset: str | None = None,
        model: str = "fal-ai/flux/dev",
        aspect_ratio: str | None = None,
    ) -> dict:
        """Generate a portrait using the user's trained Digital Twin LoRA.

        Pass `digital_twin_profile_id` to target a specific trained profile,
        otherwise the active default profile is used. `enhancement_preset`
        selects a realism refinement preset (when present).
        """
        client = _client()
        try:
            payload = _drop_none({
                "prompt": prompt,
                "model": model,
                "aspect_ratio": aspect_ratio,
                "useDigitalTwin": True,
                "digitalTwinProfileId": digital_twin_profile_id,
                "digitalTwinEnhancementPreset": enhancement_preset,
            })
            return await client.generate_image(payload)
        finally:
            await client.aclose()

    @mcp.tool(name="studio_ugc_room")
    async def studio_ugc_room(
        prompt: str,
        product_image_url: str | None = None,
        room_style: str | None = None,
        model: str = "fal-ai/flux/dev",
        aspect_ratio: str | None = None,
    ) -> dict:
        """UGC-style room scene with optional product placement.

        `room_style` is a free-form descriptor (e.g. "minimalist bedroom",
        "cluttered college dorm"). WM Studio's UGC compose-prompt route
        refines the final prompt downstream.
        """
        client = _client()
        try:
            metadata: dict[str, Any] = {"toolId": "ugc_room"}
            if room_style:
                metadata["roomStyle"] = room_style
            payload = _drop_none({
                "prompt": prompt,
                "model": model,
                "aspect_ratio": aspect_ratio,
                "imageUrl": product_image_url,
                "metadata": metadata,
            })
            return await client.generate_image(payload)
        finally:
            await client.aclose()

    @mcp.tool(name="studio_convert_to_3d")
    async def studio_convert_to_3d(
        image_url: str,
        model: str = "fal-ai/hunyuan3d/v2",
    ) -> dict:
        """Convert a 2D image into a 3D GLB model (Hunyuan3D v2 by default).

        Returns `{ is3D: true, modelGlbUrl, thumbnailUrl, modelUrls, textureUrls }`
        on success. `image_url` should be a publicly accessible PNG/JPG.
        """
        client = _client()
        try:
            payload = {
                "model": model,
                "imageUrl": image_url,
                "prompt": "",
                "metadata": {"toolId": "convert_to_3d", "is3D": True},
            }
            return await client.generate_image(payload)
        finally:
            await client.aclose()

    # ---------- Video ----------

    @mcp.tool(name="studio_generate_video")
    async def studio_generate_video(
        prompt: str,
        model: str = "fal-ai/kling-video/v2.5-turbo/pro/text-to-video",
        image_url: str | None = None,
        aspect_ratio: str | None = None,
        duration: int | None = None,
    ) -> dict:
        """Generate a video (text-to-video or image-to-video).

        Pass `image_url` to enable image-to-video on supported models.
        `duration` is seconds (model-dependent, typically 5–10).
        """
        client = _client()
        try:
            payload = _drop_none({
                "prompt": prompt,
                "model": model,
                "imageUrl": image_url,
                "aspect_ratio": aspect_ratio,
                "duration": duration,
            })
            return await client.generate_video(payload)
        finally:
            await client.aclose()

    @mcp.tool(name="studio_video_enhance")
    async def studio_video_enhance(
        video_url: str,
        upscale_factor: int = 2,
        target_fps: int | None = None,
        model: str = "fal-ai/topaz/upscale/video",
    ) -> dict:
        """Upscale and optionally re-time a video via Topaz Video AI."""
        client = _client()
        try:
            payload = _drop_none({
                "model": model,
                "videoUrl": video_url,
                "upscale_factor": upscale_factor,
                "target_fps": target_fps,
            })
            return await client.upscale_video(payload)
        finally:
            await client.aclose()

    # ---------- Lifecycle ----------

    @mcp.tool(name="studio_job_status")
    async def studio_job_status(job_id: str) -> dict:
        """Get the current snapshot of an async generation job.

        Returns `{ id, status, progress, step, type, model, resultUrl,
        error, createdAt, updatedAt, events }`. Status values:
        `queued | processing | completed | failed | cancelled`.
        """
        client = _client()
        try:
            return await client.get_job(job_id)
        finally:
            await client.aclose()

    @mcp.tool(name="studio_credits_balance")
    async def studio_credits_balance() -> dict:
        """Return the authenticated user's credit balance.

        `{ balanceCredits, freeCredits, totalBalance, hasCredits }`.
        """
        client = _client()
        try:
            return await client.credits_balance()
        finally:
            await client.aclose()

    # Silence unused-warning for tools that lint-tooling sometimes flags.
    _ = (
        studio_generate_image,
        studio_upscale_image,
        studio_camera_angles,
        studio_brandshot,
        studio_casting,
        studio_digital_twin,
        studio_ugc_room,
        studio_convert_to_3d,
        studio_generate_video,
        studio_video_enhance,
        studio_job_status,
        studio_credits_balance,
        _safe_call,
    )
