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
from src.wmstudio_client import (
    InsufficientCreditsError,
    WMStudioClient,
    WMStudioClientError,
    get_user_wmstudio_client,
)

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


def _upload_required(asset_kind: str, param_name: str, reason: str = "missing") -> dict[str, Any]:
    """Return a structured "please upload" response when the caller has no
    public URL for an image/video. Claude can render `uploadUrl` as a link.

    The default `uploadUrl` is director-cut's public drag-and-drop page at
    `https://director-cut.fly.dev/upload`, which uploads to fal's CDN and
    returns a stable URL ready to paste into the next tool call. Override
    via the `ASSET_UPLOAD_URL` env var.
    """
    upload_url = get_settings().asset_upload_url
    if reason == "unreachable":
        msg = (
            f"The {asset_kind} URL provided is not reachable (404 or DNS failure). "
            f"DO NOT invent or guess another URL. Ask the user to drag-and-drop "
            f"their {asset_kind} at {upload_url} and paste the URL the page returns."
        )
    else:
        msg = (
            f"This tool needs a publicly accessible {asset_kind} URL via `{param_name}`. "
            f"DO NOT fabricate a URL. If the user has not provided one, send them to "
            f"{upload_url} to drag-and-drop the file — the page returns a real CDN URL."
        )
    return {
        "ok": False,
        "error": "asset_url_required",
        "param": param_name,
        "assetKind": asset_kind,
        "reason": reason,
        "uploadUrl": upload_url,
        "message": msg,
    }


# Public/CDN hosts we know are real and skip the preflight check for.
_TRUSTED_ASSET_HOSTS = (
    "fal.media",
    "fal.run",
    "cdn.wmstudio",
    "wmstudio.io",
    "director-cut.fly.dev",
    "supabase.co",
)


def _upgrade_required(payload: Any) -> dict[str, Any]:
    """Structured response when wmstudio rejects with HTTP 402 (insufficient credits).

    Claude renders `upgradeUrl` as a clickable link. The flat `error` /
    `message` fields are designed so Claude stops the workflow loop —
    further tool calls before topping up will hit the same wall.
    """
    upgrade_url = get_settings().credits_upgrade_url
    body = payload if isinstance(payload, dict) else {}
    required = body.get("requiredCredits") or body.get("requiredCost")
    available = body.get("availableCredits") or body.get("balanceCredits")
    return {
        "ok": False,
        "error": "upgrade_required",
        "reason": "insufficient_credits",
        "upgradeUrl": upgrade_url,
        "requiredCredits": required,
        "availableCredits": available,
        "message": (
            f"You don't have enough credits for this generation"
            + (f" (needs {required}, have {available})" if required and available is not None else "")
            + f". Upgrade or top up at {upgrade_url}, then retry. "
            f"DO NOT call further generation tools until credits are added."
        ),
    }


async def _attach_credit_status(client: WMStudioClient, result: dict[str, Any]) -> dict[str, Any]:
    """Best-effort: append `creditsRemaining` + low-credit warning to a successful tool response.

    Failure to fetch the balance must NEVER fail the tool — generation already
    succeeded. We swallow errors silently and log at debug level.
    """
    try:
        bal = await client.credits_balance()
    except Exception as e:  # noqa: BLE001 — non-critical post-generation step
        log.debug("post_generation_balance_fetch_failed", error=str(e)[:120])
        return result
    settings = get_settings()
    total = bal.get("totalBalance")
    if total is None:
        total = bal.get("balanceCredits")
    if total is None:
        return result
    try:
        total_int = int(total)
    except (TypeError, ValueError):
        return result
    result["creditsRemaining"] = total_int
    if total_int <= settings.credits_low_threshold:
        result["lowCreditsWarning"] = True
        result["upgradeUrl"] = settings.credits_upgrade_url
        result["lowCreditsMessage"] = (
            f"Only {total_int} credits remaining. Top up at {settings.credits_upgrade_url} "
            f"to avoid interruption on the next generation."
        )
    return result


async def _preview_or_run(
    client: WMStudioClient,
    op,  # type: ignore[no-untyped-def] — bound coroutine method
    payload: dict[str, Any],
    *,
    confirm: bool,
    operation_label: str,
) -> dict[str, Any]:
    """Two-phase confirmation pattern for billed operations.

    When `confirm=False` (default): fetch a cost estimate from the wmstudio
    pricing endpoint and return a structured `preview` response. The agent
    is expected to surface the credit cost to the user and re-call with
    `confirm=True`.

    When `confirm=True`: run the actual billed operation via `_run_billed`.

    The preview includes `requiresConfirmation: True` and a `message` the
    agent can read aloud verbatim.
    """
    if confirm:
        return await _run_billed(client, op, payload)

    try:
        estimate = await client.estimate_pricing(payload)
    except WMStudioClientError as e:
        log.warning(
            "preview_pricing_failed",
            operation=operation_label,
            status=e.status_code,
            message=str(e.message)[:200],
        )
        # No estimate — still ask for confirmation but without a number.
        return {
            "ok": True,
            "preview": True,
            "requiresConfirmation": True,
            "operation": operation_label,
            "estimatedCredits": None,
            "estimatedCostUsd": None,
            "message": (
                f"You're about to run `{operation_label}`. The cost estimate is "
                f"unavailable right now. Ask the user to confirm, then re-call this "
                f"tool with `confirm=True` to proceed."
            ),
        }

    credits = estimate.get("credits")
    cost_usd = estimate.get("costUSD")
    return {
        "ok": True,
        "preview": True,
        "requiresConfirmation": True,
        "operation": operation_label,
        "estimatedCredits": credits,
        "estimatedCostUsd": cost_usd,
        "message": (
            f"You are going to spend ~{credits} credits"
            + (f" (~${cost_usd:.3f})" if isinstance(cost_usd, (int, float)) else "")
            + f" for `{operation_label}`. Confirm with the user before proceeding. "
            f"If they accept, re-call this exact tool with `confirm=True`."
        ),
    }


async def _run_billed(
    client: WMStudioClient,
    op,  # type: ignore[no-untyped-def] — bound coroutine method
    *args: Any,
) -> dict[str, Any]:
    """Run a billed wmstudio operation with credit-aware error handling.

    - HTTP 402 (`requiresTopUp: true`) → structured upgrade response (no exception).
    - Success → response is augmented with `creditsRemaining` + low-credit warning.
    - Other upstream errors propagate as `WMStudioClientError` for the tool's
      own catch (or surface as MCP error).
    """
    try:
        result = await op(*args)
    except InsufficientCreditsError as e:
        log.info(
            "studio_tool_insufficient_credits",
            payload_keys=list(e.payload.keys()) if isinstance(e.payload, dict) else None,
        )
        return _upgrade_required(e.payload)
    if not isinstance(result, dict):
        return result  # type: ignore[unreachable]
    return await _attach_credit_status(client, result)


async def _gate_asset_url(
    url: str | None,
    *,
    asset_kind: str,
    param: str,
    required: bool,
) -> dict[str, Any] | None:
    """Single gate every studio tool uses for asset URLs.

    - If `required` and url is missing → return upload-required response.
    - If url is present but unreachable → return upload-required (reason=unreachable).
    - If url is missing but optional (text-to-X workflows) → return None (proceed).

    Returning a dict means the tool should short-circuit and return it as-is.
    """
    if not url:
        if required:
            return _upload_required(asset_kind, param)
        return None
    if not await _verify_asset_url(url):
        return _upload_required(asset_kind, param, reason="unreachable")
    return None


async def _verify_asset_url(url: str) -> bool:
    """Quick HEAD probe so we reject fabricated URLs before billing the user.

    Returns True on 2xx/3xx, False on 4xx/5xx/DNS/timeout. Trusted hosts
    short-circuit to True (we know the CDN serves them).
    """
    try:
        from urllib.parse import urlparse

        host = (urlparse(url).hostname or "").lower()
        if any(host.endswith(t) for t in _TRUSTED_ASSET_HOSTS):
            return True
        import httpx

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(5.0, connect=3.0), follow_redirects=True
        ) as client:
            r = await client.head(url)
            if r.status_code == 405:  # HEAD not allowed; fall through to GET range
                r = await client.get(url, headers={"Range": "bytes=0-0"})
            return r.status_code < 400
    except Exception:  # noqa: BLE001 — any failure means "don't trust it"
        return False


def register(mcp: FastMCP) -> None:
    # ---------- Image generation ----------

    @mcp.tool(name="studio_generate_image")
    async def studio_generate_image(
        prompt: str,
        confirm: bool = False,
        model: str | None = None,
        aspect_ratio: str | None = None,
        image_url: str | None = None,
        negative_prompt: str | None = None,
        num_images: int | None = None,
        seed: int | None = None,
    ) -> dict:
        """Generate an image with WM Studio via fal.ai.

        TWO-PHASE CONFIRMATION (REQUIRED — do not skip):
          1. Call this tool WITHOUT `confirm` (or `confirm=False`) → returns a
             `preview` with `estimatedCredits`. Show that cost to the user
             verbatim and ASK: "You are going to spend X credits. Proceed?".
          2. Only AFTER the user agrees, re-call with `confirm=True` to
             actually generate the image. NEVER set `confirm=True` on your
             own initiative.

        Defaults to `fal-ai/nano-banana-pro` (text-to-image), auto-switching
        to `fal-ai/nano-banana-pro/edit` when `image_url` is provided.
        Returns `{ imageUrl, images, generationId, requestId, creditsCharged,
        creditsRemaining }` on success.

        If `image_url` is provided it MUST be a real URL the user gave you;
        never fabricate one.
        """
        gate = await _gate_asset_url(image_url, asset_kind="image", param="image_url", required=False)
        if gate:
            return gate

        # Default model: edit variant for img2img, base variant for t2i.
        resolved_model = model or (
            "fal-ai/nano-banana-pro/edit" if image_url else "fal-ai/nano-banana-pro"
        )

        client = _client()
        try:
            payload = _drop_none({
                "prompt": prompt,
                "model": resolved_model,
                "aspect_ratio": aspect_ratio,
                "imageUrl": image_url,
                "negative_prompt": negative_prompt,
                "num_images": num_images,
                "seed": seed,
            })
            return await _preview_or_run(
                client,
                client.generate_image,
                payload,
                confirm=confirm,
                operation_label=f"image generation · {resolved_model}",
            )
        finally:
            await client.aclose()

    @mcp.tool(name="studio_upscale_image")
    async def studio_upscale_image(
        image_url: str | None = None,
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

        IMPORTANT: `image_url` MUST be a real URL the user gave you. NEVER
        invent, guess, or construct a URL (no fake S3, no placeholders). If
        the user has not provided a URL, call this tool with `image_url`
        omitted to receive a public upload link to give them.
        """
        gate = await _gate_asset_url(image_url, asset_kind="image", param="image_url", required=True)
        if gate:
            return gate
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
            return await _run_billed(client, client.generate_image, payload)
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

        IMPORTANT: This tool conditions on a reference image. `image_url`
        MUST be a real URL. If the user hasn't provided one, omit it to
        receive the upload link to share with them — NEVER fabricate URLs.
        """
        gate = await _gate_asset_url(image_url, asset_kind="image", param="image_url", required=True)
        if gate:
            return gate
        client = _client()
        try:
            payload = _drop_none({
                "prompt": prompt,
                "model": model,
                "aspect_ratio": aspect_ratio,
                "imageUrl": image_url,
                "metadata": {"toolId": "camera_angles", "camera": camera},
            })
            return await _run_billed(client, client.generate_image, payload)
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
        """Brand-consistent product/marketing shot.

        Pass the product image and an optional brand color palette (hex
        strings). IMPORTANT: `product_image_url` MUST be a real URL the
        user gave you. NEVER fabricate URLs — if the user has not provided
        one, omit `product_image_url` to receive the upload link to give
        them.
        """
        gate = await _gate_asset_url(
            product_image_url, asset_kind="image", param="product_image_url", required=True
        )
        if gate:
            return gate
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
            return await _run_billed(client, client.generate_image, payload)
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
            return await _run_billed(client, client.generate_image, payload)
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
            return await _run_billed(client, client.generate_image, payload)
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
        """UGC-style room scene with product placement.

        `room_style` is a free-form descriptor (e.g. "minimalist bedroom",
        "cluttered college dorm"). WM Studio's UGC compose-prompt route
        refines the final prompt downstream.

        IMPORTANT: `product_image_url` MUST be a real URL the user gave you.
        NEVER fabricate URLs — omit it to receive the upload link.
        """
        gate = await _gate_asset_url(
            product_image_url, asset_kind="image", param="product_image_url", required=True
        )
        if gate:
            return gate
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
            return await _run_billed(client, client.generate_image, payload)
        finally:
            await client.aclose()

    @mcp.tool(name="studio_convert_to_3d")
    async def studio_convert_to_3d(
        image_url: str | None = None,
        model: str = "fal-ai/meshy/v6/image-to-3d",
    ) -> dict:
        """Convert a 2D image into a 3D GLB model (Meshy v6 by default).

        Returns `{ is3D: true, modelGlbUrl, thumbnailUrl, modelUrls, textureUrls }`
        on success. Meshy v6 is the only 3D model wmstudio currently has a
        dedicated handler for — other fal 3D endpoints will fail validation.

        IMPORTANT: `image_url` MUST be a real URL the user gave you. NEVER
        fabricate URLs. If the user has not provided one, omit `image_url`
        to receive a public upload link to share with them.
        """
        gate = await _gate_asset_url(image_url, asset_kind="image", param="image_url", required=True)
        if gate:
            return gate
        client = _client()
        try:
            payload = {
                "model": model,
                "imageUrl": image_url,
                "prompt": "",
                "metadata": {"toolId": "convert_to_3d", "is3D": True},
            }
            return await _run_billed(client, client.generate_image, payload)
        finally:
            await client.aclose()

    # ---------- Video ----------

    @mcp.tool(name="studio_generate_video")
    async def studio_generate_video(
        prompt: str,
        confirm: bool = False,
        model: str = "bytedance/seedance-2.0-fast",
        image_url: str | None = None,
        aspect_ratio: str | None = None,
        duration: int | None = None,
        resolution: str | None = None,
    ) -> dict:
        """Generate a video (text-to-video or image-to-video).

        TWO-PHASE CONFIRMATION (REQUIRED — do not skip):
          1. Call WITHOUT `confirm` first → returns a `preview` with
             `estimatedCredits`. Show that cost to the user verbatim and
             ASK: "You are going to spend X credits. Proceed?".
          2. Only AFTER the user agrees, re-call with `confirm=True` to
             actually generate the video. NEVER set `confirm=True` on your
             own initiative.

        Defaults to `bytedance/seedance-2.0-fast` (Seedance 2.0 Fast,
        720p, ~5s). Pass `image_url` for image-to-video on supported models.
        `duration` is seconds (model-dependent, typically 5–10).
        `resolution` is one of `480p | 720p | 1080p` (model-dependent;
        Seedance 2.0 Fast tops out at 720p).

        If `image_url` is provided it MUST be a real URL the user gave you;
        never fabricate one.
        """
        gate = await _gate_asset_url(image_url, asset_kind="image", param="image_url", required=False)
        if gate:
            return gate
        client = _client()
        try:
            payload = _drop_none({
                "prompt": prompt,
                "model": model,
                "imageUrl": image_url,
                "aspect_ratio": aspect_ratio,
                "duration": duration,
                "resolution": resolution,
            })
            return await _preview_or_run(
                client,
                client.generate_video,
                payload,
                confirm=confirm,
                operation_label=(
                    f"video generation · {model}"
                    + (f" · {duration}s" if duration else "")
                ),
            )
        finally:
            await client.aclose()

    @mcp.tool(name="studio_video_enhance")
    async def studio_video_enhance(
        video_url: str | None = None,
        upscale_factor: int = 2,
        target_fps: int | None = None,
        model: str = "fal-ai/topaz/upscale/video",
    ) -> dict:
        """Upscale and optionally re-time a video via Topaz Video AI.

        IMPORTANT: `video_url` MUST be a real URL the user gave you. NEVER
        fabricate URLs. If the user has not provided one, omit `video_url`
        to receive a public upload link to share with them.
        """
        gate = await _gate_asset_url(video_url, asset_kind="video", param="video_url", required=True)
        if gate:
            return gate
        client = _client()
        try:
            payload = _drop_none({
                "model": model,
                "videoUrl": video_url,
                "upscale_factor": upscale_factor,
                "target_fps": target_fps,
            })
            return await _run_billed(client, client.upscale_video, payload)
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

    @mcp.tool(name="studio_web_search")
    async def studio_web_search(
        query: str,
        max_results: int | None = 5,
        search_depth: str | None = "basic",
        time_range: str | None = None,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
    ) -> dict:
        """Search the web (Tavily-powered) via the WM Studio backend.

        Costs 1 credit (basic) or 2 credits (advanced). The user is only
        charged on success — failed searches do not deduct credits.

        Returns:
          {
            v: 1,
            answer: string | null,           # Tavily's direct answer when available
            results: [{ title, url, content, score? }],
            images: string[],
            followUpQuestions: string[],
            creditsCharged: number,
            creditsRemaining: number,
          }

        Args:
          query: search string (1–400 chars).
          max_results: 1–10 (default 5).
          search_depth: "basic" | "advanced" — advanced is slower but more
                        thorough and costs 2 credits.
          time_range: "day" | "week" | "month" | "year" to filter by recency.
          include_domains: only return results from these domains.
          exclude_domains: skip results from these domains.

        Use this when:
          - The user asks for current/recent information.
          - Your training data may be stale (post-cutoff news, releases, prices).
          - You need authoritative sources to cite back.
        """
        client = _client()
        try:
            payload = _drop_none({
                "query": query,
                "maxResults": max_results,
                "searchDepth": search_depth,
                "timeRange": time_range,
                "includeDomains": include_domains,
                "excludeDomains": exclude_domains,
            })
            return await client.web_search(payload)
        except WMStudioClientError as e:
            log.warning(
                "studio_web_search_upstream_error",
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
        studio_web_search,
        studio_credits_balance,
        _safe_call,
    )
