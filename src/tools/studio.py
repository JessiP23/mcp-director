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

import asyncio
import base64
import json
from typing import Any, Optional

import httpx
import structlog
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_request
from mcp.types import CallToolResult, ImageContent, TextContent

from src.config import get_settings
from src.wmstudio_client import (
    InsufficientCreditsError,
    WMStudioClient,
    WMStudioClientError,
    get_user_wmstudio_client,
)

log = structlog.get_logger(__name__)


def _wmstudio_base_url() -> str:
    settings = get_settings()
    return settings.wmstudio_api_url.rstrip("/")


async def _save_character_asset(
    character_name: str,
    prompt: str,
    character_profile: dict[str, Any] | None,
    result: dict[str, Any],
    director_run_id: str,
    director_event_id: str,
    model: str,
) -> None:
    """Save character asset to the character_assets table after successful generation.

    This is called synchronously after studio_casting generations to persist
    character assets for later reference. Errors are logged but don't fail
    the generation flow.

    Uses direct Supabase REST API with anon key only.
    """
    log.info(
        "character_asset_save_called",
        character_name=character_name,
        director_run_id=director_run_id,
        director_event_id=director_event_id,
    )

    try:
        # Get user_id from request state for RLS policy compliance
        request = get_http_request()
        user_id = getattr(request.state, "user_id", None)
        log.info(
            "character_asset_user_id_check",
            director_run_id=director_run_id,
            has_user_id=user_id is not None,
            user_id=user_id,
        )

        settings = get_settings()
        supabase_url = settings.supabase_url.rstrip("/")
        supabase_anon_key = settings.supabase_anon_key

        # Extract image URL from result
        image_url = result.get("imageUrl") or result.get("image_url")
        generation_id = result.get("generationId") or result.get("id")

        # Use Supabase REST API to insert character asset
        url = f"{supabase_url}/rest/v1/character_assets"
        payload = {
            "user_id": user_id,
            "director_run_id": director_run_id,
            "director_event_id": director_event_id,
            "character_name": character_name,
            "character_profile": character_profile or {},
            "prompt": prompt,
            "model_endpoint": model,
            "generation_id": generation_id,
            "image_url": image_url,
            "output_metadata": result,
        }

        log.info(
            "character_asset_sending_supabase_request",
            url=url,
            payload_keys=list(payload.keys()),
            has_image_url=bool(image_url),
        )

        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={
                    "apikey": supabase_anon_key,
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal",
                },
            )
            log.info(
                "character_asset_supabase_response_received",
                status_code=resp.status_code,
                response_body=(resp.text or "")[:500],
            )

            if resp.status_code >= 400:
                log.warning(
                    "character_asset_save_failed",
                    director_run_id=director_run_id,
                    director_event_id=director_event_id,
                    status=resp.status_code,
                    response_body=(resp.text or "")[:200],
                )
            else:
                log.info(
                    "character_asset_save_success",
                    director_run_id=director_run_id,
                    director_event_id=director_event_id,
                    character_name=character_name,
                )
    except Exception as exc:  # noqa: BLE001
        log.error(
            "character_asset_save_error",
            director_run_id=director_run_id,
            director_event_id=director_event_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )


async def _update_brief_after_generation(
    tool_name: str,
    prompt: str,
    result: dict[str, Any],
    director_run_id: str | None = None,
    character_name: str | None = None,
) -> None:
    """Update the production brief after a successful generation.

    This is called automatically after studio tool generations to keep
    the brief in sync with what's being created. Errors are logged but
    don't fail the generation flow.
    """
    log.info(
        "brief_update_called",
        tool=tool_name,
        director_run_id=director_run_id,
        has_director_run_id=bool(director_run_id),
        character_name=character_name,
    )

    if not director_run_id:
        log.warning("brief_update_skipped_no_director_run_id", tool=tool_name)
        return

    try:
        # Extract key information from the result
        brief_update: dict[str, Any] = {
            "reason": f"Generated content via {tool_name}",
        }

        # Add tool-specific information to brief sections
        if tool_name == "studio_casting":
            # Use provided character_name, or try to extract from metadata/userPrompt
            if not character_name:
                metadata = result.get("metadata", {})
                character_name = metadata.get("characterName") or result.get("userPrompt", "Unknown character")
            
            # Extract image URL from result
            image_url = result.get("imageUrl") or result.get("image_url")
            
            # Build character description as readable markdown with image
            character_description = prompt
            if image_url:
                character_description += f"\n\n![{character_name}]({image_url})"
            
            brief_update["sections"] = {
                "characters": {character_name: character_description}
            }
            log.info(
                "brief_update_casting_payload",
                character_name=character_name,
                prompt_length=len(prompt),
                sections=brief_update.get("sections"),
            )
        elif tool_name == "studio_generate_image":
            image_url = result.get("imageUrl") or result.get("image_url")
            visual_text = f"Generated image: {prompt[:200]}"
            if image_url:
                visual_text += f"\n\n![Generated image]({image_url})"
            brief_update["sections"] = {
                "visualLanguage": visual_text
            }
        elif tool_name == "studio_camera_angles":
            brief_update["sections"] = {
                "visualLanguage": f"Camera angles: {prompt[:200]}"
            }
        elif tool_name == "studio_brandshot":
            brief_update["sections"] = {
                "visualLanguage": f"Brandshot: {prompt[:200]}"
            }
        elif tool_name == "studio_digital_twin":
            brief_update["sections"] = {
                "visualLanguage": f"Digital twin: {prompt[:200]}"
            }
        elif tool_name == "studio_ugc_room":
            brief_update["sections"] = {
                "locations": {f"UGC room: {prompt[:100]}": prompt}
            }

        # Make async HTTP request to brief API
        url = f"{_wmstudio_base_url()}/api/director/{director_run_id}/brief"
        log.info(
            "brief_update_sending_request",
            tool=tool_name,
            director_run_id=director_run_id,
            url=url,
            payload_keys=list(brief_update.keys()),
        )

        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
            resp = await client.patch(
                url,
                json={
                    "directorRunId": director_run_id,
                    **brief_update,
                },
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "mcp-director/studio-tools",
                },
            )
            log.info(
                "brief_update_response_received",
                tool=tool_name,
                director_run_id=director_run_id,
                status_code=resp.status_code,
                response_body=(resp.text or "")[:500],
            )

            if resp.status_code >= 400:
                log.warning(
                    "brief_update_after_generation_failed",
                    tool=tool_name,
                    director_run_id=director_run_id,
                    status=resp.status_code,
                    response_body=(resp.text or "")[:200],
                )
            else:
                log.info(
                    "brief_update_after_generation_success",
                    tool=tool_name,
                    director_run_id=director_run_id,
                    response_body=(resp.text or "")[:200],
                )
    except Exception as exc:  # noqa: BLE001
        log.error(
            "brief_update_after_generation_error",
            tool=tool_name,
            director_run_id=director_run_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )


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


def _clean_false_params(d: dict[str, Any]) -> dict[str, Any]:
    """Convert False values to None for optional string parameters.
    
    This handles cases where the LLM passes False for optional parameters
    instead of omitting them, which causes Pydantic validation errors.
    """
    result = {}
    for k, v in d.items():
        # Convert False to None for common optional parameters
        if v is False and k in ["model", "image_url", "negative_prompt", "seed", "aspect_ratio", "duration", "resolution"]:
            result[k] = None
        else:
            result[k] = v
    return result


async def _is_director_run_cancelled(director_run_id: str) -> bool:
    """Check if a Director run has been cancelled via the MCP server."""
    try:
        from fastmcp.server.dependencies import get_http_request
        request = get_http_request()
        if not request:
            return False

        # Access Redis from app state
        from fastapi import Request
        app = request.scope.get("app")
        if not app:
            return False

        redis = getattr(app.state, "redis", None)
        if not redis:
            log.warning("_is_director_run_cancelled_no_redis")
            return False

        key = f"cancelled_director_run:{director_run_id}"
        is_cancelled = await redis.exists(key)
        if is_cancelled:
            log.info("_is_director_run_cancelled_true", director_run_id=director_run_id)
        return bool(is_cancelled)
    except Exception as e:
        log.warning("_is_director_run_cancelled_failed", error=str(e))
        return False


def _extract_director_metadata(
    directorRunId: str | None = None,
    directorEventId: str | None = None,
    directorToolName: str | None = None,
) -> dict[str, Any]:
    """Extract Director metadata from tool arguments and return it.

    The wmstudio production-agent injects directorRunId, directorEventId,
    and directorToolName into studio tool calls. We need to forward these
    to the wmstudio API so it can skip normal authentication.
    """
    import structlog
    log = structlog.get_logger(__name__)

    # Also try to get from request context as fallback
    try:
        request = get_http_request()
        if request:
            # Check if Director metadata is in request state (set by middleware)
            ctx_run_id = getattr(request.state, "director_run_id", None)
            ctx_event_id = getattr(request.state, "director_event_id", None)
            ctx_tool_name = getattr(request.state, "director_tool_name", None)
            log.info(
                "_extract_director_metadata_from_request_state",
                ctx_run_id=ctx_run_id,
                ctx_event_id=ctx_event_id,
                ctx_tool_name=ctx_tool_name,
            )
            if ctx_run_id and ctx_event_id and ctx_tool_name:
                log.info("_extract_director_metadata_success_from_state")
                return {
                    "directorRunId": ctx_run_id,
                    "directorEventId": ctx_event_id,
                    "directorToolName": ctx_tool_name,
                }
    except RuntimeError as e:
        # No HTTP request context available
        log.info("_extract_director_metadata_no_request_context", error=str(e))
        pass

    log.info(
        "_extract_director_metadata_from_params",
        directorRunId=directorRunId,
        directorEventId=directorEventId,
        directorToolName=directorToolName,
    )
    if directorRunId and directorEventId and directorToolName:
        log.info("_extract_director_metadata_success_from_params")
        return {
            "directorRunId": directorRunId,
            "directorEventId": directorEventId,
            "directorToolName": directorToolName,
        }
    log.info("_extract_director_metadata_empty")
    return {}


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
    resolve_kind: str | None = None,
    extra_structured: dict[str, Any] | None = None,
    director_run_id: str | None = None,
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
    # Check if the Director run has been cancelled before executing
    if director_run_id and await _is_director_run_cancelled(director_run_id):
        log.info("_preview_or_run_cancelled", director_run_id=director_run_id)
        return {
            "ok": False,
            "error": "cancelled",
            "message": "Director run was cancelled by the user",
            "directorRunId": director_run_id,
        }

    if confirm:
        return await _run_billed(client, op, payload, resolve_kind=resolve_kind, extra_structured=extra_structured, director_run_id=director_run_id)

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
            "message": (
                f"You're about to run `{operation_label}`. The cost estimate is "
                f"unavailable right now. Ask the user to confirm, then re-call this "
                f"tool with `confirm=True` to proceed."
            ),
        }

    credits = estimate.get("credits")
    return {
        "ok": True,
        "preview": True,
        "requiresConfirmation": True,
        "operation": operation_label,
        "estimatedCredits": credits,
        "message": (
            f"You are going to spend ~{credits} credits"
            f" for `{operation_label}`. Confirm with the user before proceeding. "
            f"If they accept, re-call this exact tool with `confirm=True`."
        ),
    }


# ---------------------------------------------------------------------------
# Inline image rendering
#
# Claude Desktop (and MCP-compliant clients) renders `ImageContent` blocks
# inline, so the user sees the actual image instead of a clickable URL.
# The trade-off is bandwidth: the MCP server downloads the bytes from R2
# and base64-encodes them. We cap the size and stream so a single tool
# call never blows up memory.
#
# Videos are NOT inlined (no ImageContent for video in MCP); we just
# embed a markdown link in a TextContent block so it renders nicely.
# ---------------------------------------------------------------------------

# Soft cap: anything larger than this falls back to a URL-only response
# so the JSON-RPC payload stays well under client limits.
_INLINE_IMAGE_MAX_BYTES = 6 * 1024 * 1024  # 6 MiB
_INLINE_IMAGE_TIMEOUT_S = 20.0


async def _fetch_image_bytes(url: str) -> tuple[bytes, str] | None:
    """Download `url` and return `(bytes, mime_type)` or None on any failure.

    Uses a fresh httpx client (no auth headers — R2 public URLs are open).
    Caps download at `_INLINE_IMAGE_MAX_BYTES` so an oversized asset
    aborts cleanly instead of OOM'ing the server.
    """
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(_INLINE_IMAGE_TIMEOUT_S, connect=5.0),
            follow_redirects=True,
        ) as http:
            async with http.stream("GET", url) as resp:
                if resp.status_code != 200:
                    log.error("inline_image_bad_status", url=url, status=resp.status_code)
                    return None
                content_type = (resp.headers.get("content-type") or "image/png").split(";")[0].strip()
                if not content_type.startswith("image/"):
                    log.error("inline_image_bad_content_type", url=url, ct=content_type)
                    return None
                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > _INLINE_IMAGE_MAX_BYTES:
                        log.error("inline_image_oversize", url=url, bytes=total)
                        return None
                    chunks.append(chunk)
                return b"".join(chunks), content_type
    except (httpx.HTTPError, asyncio.TimeoutError) as e:
        log.error("inline_image_fetch_failed", url=url, err=str(e)[:200], error_type=type(e).__name__)
        return None


def _image_content(data: bytes, mime_type: str) -> ImageContent:
    return ImageContent(
        type="image",
        data=base64.b64encode(data).decode("ascii"),
        mimeType=mime_type,
    )


async def _render_with_inline_image(structured: dict[str, Any]) -> Any:
    """Wrap a single-image generation response so Claude renders it inline.

    Returns either:
      - the original dict unchanged (no URL, fetch failed, or oversize), OR
      - a CallToolResult with ImageContent + TextContent so MCP clients render
        the image inline AND keep the structured fields (creditsRemaining,
        generationId, etc.) accessible to the agent.
    """
    if not isinstance(structured, dict):
        return structured
    url = _extract_image_url(structured)
    if not url:
        log.warning("inline_render_no_url", structured_keys=list(structured.keys()))
        return structured
    fetched = await _fetch_image_bytes(url)
    if fetched is None:
        log.error("inline_render_fetch_failed", url=url, structured_keys=list(structured.keys()))
        # Add error info to structured response so user knows why image isn't showing
        error_structured = dict(structured)
        error_structured["_inlineImageError"] = "Failed to fetch image for inline rendering"
        return error_structured
    data, mime = fetched
    content_blocks: list[Any] = [
        _image_content(data, mime),
        TextContent(type="text", text=json.dumps(structured, default=str)),
    ]
    return CallToolResult(
        content=content_blocks,
        structuredContent=structured,
    )


async def _render_with_inline_images(
    structured: dict[str, Any],
    *,
    url_picker,  # type: ignore[no-untyped-def] — callable extracting URLs
) -> Any:
    """Storyboard variant: render multiple frame images inline in order.

    `url_picker(structured) -> list[str]` returns each frame URL. Frames
    are downloaded in parallel; any failure falls back to URL-only for
    that frame (the structured response still includes them all).
    """
    if not isinstance(structured, dict):
        return structured
    urls: list[str] = url_picker(structured) or []
    if not urls:
        return structured
    results = await asyncio.gather(*(_fetch_image_bytes(u) for u in urls))
    blocks: list[Any] = []
    for r in results:
        if r is None:
            continue
        data, mime = r
        blocks.append(_image_content(data, mime))
    if not blocks:
        return structured
    blocks.append(TextContent(type="text", text=json.dumps(structured, default=str)))
    return blocks


def _video_markdown_block(structured: dict[str, Any]) -> TextContent | None:
    """Build a markdown TextContent block for a video URL so Claude
    renders a nice clickable preview alongside the structured payload.

    Returns None if the response has no videoUrl.
    """
    url = structured.get("videoUrl") if isinstance(structured, dict) else None
    if not isinstance(url, str) or not url:
        return None
    return TextContent(type="text", text=f"**Video ready:** [{url}]({url})")


async def _run_billed(
    client: WMStudioClient,
    op,  # type: ignore[no-untyped-def] — bound coroutine method
    *args: Any,
    resolve_kind: str | None = None,
    extra_structured: dict[str, Any] | None = None,
    director_run_id: str | None = None,
) -> Any:
    """Run a billed wmstudio operation with credit-aware error handling.

    - HTTP 402 (`requiresTopUp: true`) → structured upgrade response (no exception).
    - Success → response is augmented with `creditsRemaining` + low-credit warning.
    - Other upstream errors propagate as `WMStudioClientError` for the tool's
      own catch (or surface as MCP error).

    If `resolve_kind` is `"image"` or `"video"`, queued responses
    (`{queued: true, jobId}`) are polled via `_resolve_generation_response`
    so the tool always returns a usable asset URL instead of forcing the
    agent to chain `studio_job_status`.

    For `resolve_kind="image"` the final response is wrapped with an
    inline `ImageContent` block so Claude renders the image directly in
    chat instead of just showing a URL. For `resolve_kind="video"` we
    add a markdown link block. On any rendering failure we transparently
    fall back to the plain structured dict so the tool stays robust.
    """
    # Check if the Director run has been cancelled before executing
    if director_run_id and await _is_director_run_cancelled(director_run_id):
        log.info("_run_billed_cancelled", director_run_id=director_run_id)
        return {
            "ok": False,
            "error": "cancelled",
            "message": "Director run was cancelled by the user",
            "directorRunId": director_run_id,
        }

    try:
        result = await op(*args)
    except WMStudioClientError as e:
        # Check if this is a cancellation error
        if e.status_code == 499 and isinstance(e.payload, dict) and e.payload.get("cancelled"):
            log.info("_run_billed_cancelled_during_execution", director_run_id=director_run_id)
            return {
                "ok": False,
                "error": "cancelled",
                "message": "Director run was cancelled by the user",
                "directorRunId": director_run_id,
            }
        raise
    except InsufficientCreditsError as e:
        log.info(
            "studio_tool_insufficient_credits",
            payload_keys=list(e.payload.keys()) if isinstance(e.payload, dict) else None,
        )
        return _upgrade_required(e.payload)
    if not isinstance(result, dict):
        return result  # type: ignore[unreachable]
    if resolve_kind in ("image", "video"):
        try:
            result = await _resolve_generation_response(client, result, kind=resolve_kind, director_run_id=director_run_id)
        except WMStudioClientError as e:
            # Polling failed/timed out — credits are already spent. Surface
            # jobId so the user can recover via studio_job_status, but do not
            # claim success.
            log.warning(
                "studio_tool_resolve_failed",
                status=e.status_code,
                jobId=(result.get("jobId") if isinstance(result, dict) else None),
                message=str(e.message)[:200],
            )
            return await _attach_credit_status(client, {
                "ok": False,
                "error": "queued_unresolved",
                "jobId": result.get("jobId"),
                "creditsCharged": result.get("creditsCharged"),
                "message": str(e.message),
                "raw": result,
            })
    structured = await _attach_credit_status(client, result)
    if resolve_kind == "image" and isinstance(structured, dict) and structured.get("ok") is not False:
        return await _render_with_inline_image(structured)
    if resolve_kind == "video" and isinstance(structured, dict) and structured.get("ok") is not False:
        sc: dict[str, Any] = {
            "videoUrl": structured.get("videoUrl"),
            "model": structured.get("model"),
            "duration": structured.get("duration"),
            "resolution": structured.get("resolution"),
            "creditsCharged": structured.get("creditsCharged"),
            "creditsRemaining": structured.get("creditsRemaining"),
        }
        if extra_structured:
            for k, v in extra_structured.items():
                if v is not None and k not in sc:
                    sc[k] = v
        video_url = sc.get("videoUrl", "")
        content_blocks: list[Any] = [
            TextContent(type="text", text=f"Video ready: {video_url}" if video_url else "Video ready."),
        ]
        return CallToolResult(
            content=content_blocks,
            structuredContent=sc,
        )
    return structured


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


def _extract_image_url(payload: dict[str, Any]) -> str | None:
    """Pull the image URL out of a generate-image response (any shape)."""
    if not isinstance(payload, dict):
        return None
    direct = payload.get("imageUrl") or payload.get("resultUrl") or payload.get("outputUrl")
    if isinstance(direct, str) and direct:
        return direct
    images = payload.get("images")
    if isinstance(images, list) and images:
        first = images[0]
        if isinstance(first, dict):
            url = first.get("url") or first.get("imageUrl")
            if isinstance(url, str) and url:
                return url
        elif isinstance(first, str):
            return first
    return None


async def _resolve_queued_job(
    client: WMStudioClient,
    job_id: str,
    *,
    director_run_id: str | None = None,
    timeout_s: float = 180.0,
    initial_wait_s: float = 2.0,
    max_wait_s: float = 8.0,
) -> dict[str, Any]:
    """Poll a creative-studio job until it reaches a terminal state.

    Returns the final job snapshot. Raises `WMStudioClientError` if the job
    fails or the timeout elapses (so callers can decide whether to surface
    the jobId for later resumption).

    Credits are charged at queue submission time — a polling timeout here
    does NOT mean the user wasn't charged. The caller must include the
    `jobId` in any user-facing error so they can re-poll later.
    """
    deadline = asyncio.get_event_loop().time() + timeout_s
    wait = initial_wait_s
    last: dict[str, Any] = {}
    while True:
        # Check if the Director run has been cancelled
        if director_run_id and await _is_director_run_cancelled(director_run_id):
            log.info("_resolve_queued_job_cancelled", director_run_id=director_run_id, job_id=job_id)
            raise WMStudioClientError(
                499,
                "Director run was cancelled by the user",
                payload={"cancelled": True, "directorRunId": director_run_id, "jobId": job_id},
            )

        snapshot = await client.get_job(job_id, director_run_id=director_run_id)
        last = snapshot if isinstance(snapshot, dict) else {}
        status = last.get("status")
        if status in ("completed", "failed", "cancelled"):
            if status == "completed":
                return last
            err = last.get("error") or f"job {status}"
            raise WMStudioClientError(
                502, f"queued generation {status}: {err}", payload=last
            )
        if asyncio.get_event_loop().time() >= deadline:
            raise WMStudioClientError(
                504,
                f"queued generation still {status or 'pending'} after {timeout_s:.0f}s "
                f"(jobId={job_id}); credits already charged. Re-poll with "
                f"studio_job_status to recover the result.",
                payload=last,
            )
        await asyncio.sleep(wait)
        wait = min(wait * 1.5, max_wait_s)


async def _resolve_generation_response(
    client: WMStudioClient,
    raw: dict[str, Any],
    *,
    kind: str,
    director_run_id: str | None = None,
    timeout_s: float = 180.0,
) -> dict[str, Any]:
    """Normalize an inline OR queued generate-* response into one with the
    asset URL populated under the right key (`imageUrl` for kind="image",
    `videoUrl` for kind="video"). Credits are preserved as-is.

    - Inline response (sync fal): returns `raw` unchanged (URL already there).
    - Queued response (`queued: true` + `jobId`): polls until completed,
      then merges the resolved URL back into `raw` so callers see one shape.
    """
    if not isinstance(raw, dict):
        return raw  # type: ignore[unreachable]

    url_key = "videoUrl" if kind == "video" else "imageUrl"

    # Inline path: URL already present (either at the right key or via images[]).
    if raw.get(url_key) or (kind == "image" and _extract_image_url(raw)):
        return raw

    job_id = raw.get("jobId") or raw.get("id")
    is_queued = raw.get("queued") is True or raw.get("status") in ("queued", "processing")
    if not (is_queued and isinstance(job_id, str) and job_id):
        return raw  # nothing we can do — return as-is and let caller decide

    snapshot = await _resolve_queued_job(client, job_id, director_run_id=director_run_id, timeout_s=timeout_s)
    url = snapshot.get("resultUrl") or _extract_image_url(snapshot)
    merged = dict(raw)
    if isinstance(url, str) and url:
        merged[url_key] = url
        if kind == "image":
            merged["images"] = [{"url": url}]
    merged["jobId"] = job_id
    merged["jobStatus"] = snapshot.get("status")
    return merged


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
    # ---------- Shared image-generation options (extensible) ----------

    @mcp.resource("studio://options/image-aspect-ratios")
    def image_aspect_ratios() -> dict[str, Any]:
        """Available aspect ratios for image generation.

        Agents MUST ask the user to pick one before calling any image
        generation tool. This resource is the single source of truth —
        add new entries here and they propagate to every tool + the CLI.
        """
        return {
            "description": "Aspect ratios for image generation. Ask the user to pick one.",
            "options": [
                {"value": "1:1", "label": "Square (1:1)", "tags": ["social", "instagram"]},
                {"value": "16:9", "label": "Landscape (16:9)", "tags": ["youtube", "desktop"]},
                {"value": "9:16", "label": "Portrait (9:16)", "tags": ["stories", "mobile", "tiktok"]},
                {"value": "4:3", "label": "Classic (4:3)", "tags": ["photography"]},
                {"value": "3:4", "label": "Tall (3:4)", "tags": ["portrait", "print"]},
                {"value": "21:9", "label": "Ultrawide (21:9)", "tags": ["cinematic"]},
            ],
            "default": "1:1",
        }

    # ---------- Image generation ----------

    @mcp.tool(name="studio_generate_image")
    async def studio_generate_image(
        prompt: str,
        aspect_ratio: str,
        confirm: bool = False,
        model: str = "openai/gpt-image-2",
        negative_prompt: str | None = None,
        num_images: int | None = None,
        seed: int | None = None,
        directorRunId: str | None = None,
        directorEventId: str | None = None,
        directorToolName: str | None = None,
    ) -> dict:
        """Generate an image with WM Studio via fal.ai.

        ASPECT RATIO (REQUIRED — ask the user before calling):
          You MUST ask the user which aspect ratio they want BEFORE calling
          this tool. Available options are listed in the `studio://options/
          image-aspect-ratios` resource. Read that resource, present the
          options to the user, and pass their choice as `aspect_ratio`.
          Do NOT guess or pick a default on your own.

        TWO-PHASE CONFIRMATION (REQUIRED — do not skip):
          1. Call this tool WITHOUT `confirm` (or `confirm=False`) → returns a
             `preview` with `estimatedCredits`. Show that cost to the user
             verbatim and ASK: "You are going to spend X credits. Proceed?".
          2. Only AFTER the user agrees, re-call with `confirm=True` to
             actually generate the image. NEVER set `confirm=True` on your
             own initiative.

        Defaults to `openai/gpt-image-2` (general purpose/typography).
        Returns `{ imageUrl, images, generationId, requestId, creditsCharged,
        creditsRemaining }` on success.
        """
        # Clean up False values that should be None (happens after cancellation)
        if model is False:
            model = None
        if negative_prompt is False:
            negative_prompt = None
        if seed is False:
            seed = None
        if aspect_ratio is False:
            aspect_ratio = None
        
        # Clean up empty strings that should be None (LLM sometimes passes empty strings instead of omitting)
        if negative_prompt == "":
            negative_prompt = None
        if model == "":
            model = None

        if not aspect_ratio or ":" not in aspect_ratio:
            return {
                "ok": False,
                "error": "aspect_ratio_required",
                "message": (
                    "You must ask the user which aspect ratio they want. Read "
                    "`studio://options/image-aspect-ratios` for the list of "
                    "available options, present them to the user, and pass "
                    "their choice as `aspect_ratio` (e.g. \"16:9\")."
                ),
            }

        # Default model
        resolved_model = model or "openai/gpt-image-2"

        import structlog
        log = structlog.get_logger(__name__)
        log.info("studio_generate_image_model_used", model=resolved_model)

        client = _client()
        try:
            director_metadata = _extract_director_metadata(directorRunId, directorEventId, directorToolName)
            payload = _drop_none({
                "prompt": prompt,
                "model": resolved_model,
                "aspect_ratio": aspect_ratio,
                "negative_prompt": negative_prompt,
                "num_images": num_images,
                "seed": seed,
                **director_metadata,
            })
            result = await _preview_or_run(
                client,
                client.generate_image,
                payload,
                confirm=confirm,
                operation_label=f"image generation · {resolved_model}",
                resolve_kind="image",
                director_run_id=directorRunId,
            )
            # Update brief after successful generation (fire-and-forget)
            # result can be dict or CallToolResult, handle both
            result_dict = result if isinstance(result, dict) else (result.structuredContent if hasattr(result, "structuredContent") else {})
            if result_dict.get("ok") is not False and not result_dict.get("preview"):
                asyncio.create_task(
                    _update_brief_after_generation(
                        "studio_generate_image",
                        prompt,
                        result_dict,
                        directorRunId,
                    )
                )
            return result
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
        directorRunId: str | None = None,
        directorEventId: str | None = None,
        directorToolName: str | None = None,
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
            director_metadata = _extract_director_metadata(directorRunId, directorEventId, directorToolName)
            payload = {
                "model": model,
                "imageUrl": image_url,
                "upscale_factor": upscale_factor,
                "topazModel": topaz_model,
                "face_enhancement": face_enhancement,
                "output_format": output_format,
                "prompt": "",  # required by route shape; ignored by upscale handlers
                **director_metadata,
            }
            import structlog
            log = structlog.get_logger(__name__)
            log.info("studio_upscale_image_payload", payload=payload)
            return await _run_billed(client, client.generate_image, payload, resolve_kind="image", director_run_id=directorRunId)
        finally:
            await client.aclose()

    @mcp.tool(name="studio_casting")
    async def studio_casting(
        character_name: str,
        prompt: str,
        character_profile: Optional[dict[str, Any] | str] = None,
        confirm: bool = False,
        model: str = "fal-ai/nano-banana-pro",
        aspect_ratio: str | None = None,
        directorRunId: str | None = None,
        directorEventId: str | None = None,
        directorToolName: str | None = None,
    ) -> dict:
        """Generate a character casting shot.

        TWO-PHASE CONFIRMATION (REQUIRED — do not skip):
          1. Call this tool WITHOUT `confirm` (or `confirm=False`) → returns a
             `preview` with `estimatedCredits`. Show that cost to the user
             verbatim and ASK: "You are going to spend X credits. Proceed?".
          2. Only AFTER the user agrees, re-call with `confirm=True` to
             actually generate the image. NEVER set `confirm=True` on your
             own initiative.

        `character_profile` accepts WM Studio's casting schema keys:
        `characterType, genderIdentity, raceEthnicity, eyeColor, heightCm,
        weightKg, bodyType, hairStyle, hairTexture, hairColor, facialHair,
        outfitStyle, outfitDetails, cinematicGenre, characterArchetype,
        eraSetting`. All optional; the route sanitizes unknown keys.
        """
        import structlog
        log = structlog.get_logger(__name__)
        log.info("studio_casting_model_used", model=model, character_name=character_name)

        # Check if the Director run has been cancelled before executing
        if directorRunId and await _is_director_run_cancelled(directorRunId):
            log.info("studio_casting_cancelled", director_run_id=directorRunId)
            return {
                "ok": False,
                "error": "cancelled",
                "message": "Director run was cancelled by the user",
                "directorRunId": directorRunId,
            }

        client = _client()
        try:
            # Parse character_profile if it's a JSON string (LLM sometimes serializes dicts as strings)
            parsed_profile: dict[str, Any] | None = None
            if character_profile is not None:
                if isinstance(character_profile, str):
                    try:
                        import json
                        parsed_profile = json.loads(character_profile)
                    except json.JSONDecodeError:
                        log.warning("studio_casting_profile_parse_failed", character_profile=character_profile[:200])
                        return {
                            "ok": False,
                            "error": "Invalid JSON in character_profile parameter",
                        }
                else:
                    parsed_profile = character_profile

            director_metadata = _extract_director_metadata(directorRunId, directorEventId, directorToolName)
            metadata: dict[str, Any] = {
                "toolId": "casting",
                "characterName": character_name,
            }
            if parsed_profile:
                metadata["characterProfile"] = parsed_profile
            payload = _drop_none({
                "prompt": prompt,
                "userPrompt": character_name,
                "model": model,
                "aspect_ratio": aspect_ratio,
                "metadata": metadata,
                **director_metadata,
            })
            result = await _preview_or_run(
                client,
                client.generate_image,
                payload,
                confirm=confirm,
                operation_label=f"character casting",
                resolve_kind="image",
                director_run_id=directorRunId,
            )
            # Update brief after successful generation (fire-and-forget)
            # result can be dict or CallToolResult, handle both
            result_dict = result if isinstance(result, dict) else (result.structuredContent if hasattr(result, "structuredContent") else {})
            log.info(
                "studio_casting_result_received",
                ok=result_dict.get("ok"),
                preview=result_dict.get("preview"),
                has_director_run_id=bool(directorRunId),
                director_run_id=directorRunId,
                result_keys=list(result_dict.keys())[:20],
            )
            if result_dict.get("ok") is not False and not result_dict.get("preview"):
                log.info(
                    "studio_casting_scheduling_brief_update",
                    director_run_id=directorRunId,
                    character_name=character_name,
                )
                asyncio.create_task(
                    _update_brief_after_generation(
                        "studio_casting",
                        prompt,
                        result_dict,
                        directorRunId,
                        character_name=character_name,
                    )
                )
                # Also save to character_assets table (synchronous call)
                if directorRunId and directorEventId:
                    log.info(
                        "studio_casting_saving_character_asset",
                        director_run_id=directorRunId,
                        director_event_id=directorEventId,
                        character_name=character_name,
                    )
                    await _save_character_asset(
                        character_name=character_name,
                        prompt=prompt,
                        character_profile=parsed_profile,
                        result=result_dict,
                        director_run_id=directorRunId,
                        director_event_id=directorEventId,
                        model=model,
                    )
            else:
                log.warning(
                    "studio_casting_skipping_brief_update",
                    ok=result_dict.get("ok"),
                    preview=result_dict.get("preview"),
                    reason="result not ok or is preview",
                )
            return result
        finally:
            await client.aclose()

    # ---------- Storyboard (frame candidates for video) ----------

    @mcp.tool(
        name="studio_storyboard_frames",
        meta={"ui": {"resourceUri": "ui://wmstudio/storyboard-viewer"}},
    )
    async def studio_storyboard_frames(
        prompt: str,
        aspect_ratio: str,
        confirm: bool = False,
        n: int = 3,
        model: str | None = None,
        negative_prompt: str | None = None,
        seed: int | None = None,
        directorRunId: str | None = None,
        directorEventId: str | None = None,
        directorToolName: str | None = None,
    ) -> dict:
        """Generate N image FRAME CANDIDATES for the user to choose from
        before running a video generation.

        REQUIRED FIRST STEP FOR VIDEO REQUESTS. Whenever the user asks for a
        video, you MUST call this tool first to produce 2–4 still-frame
        options, present every returned `imageUrl` to the user, ask which
        ONE they want animated, and ONLY THEN call `studio_generate_video`
        with that chosen URL as `image_url`.

        ASPECT RATIO (REQUIRED — ask the user before calling):
          You MUST ask the user which aspect ratio they want BEFORE calling
          this tool. Available options are listed in the `studio://options/
          image-aspect-ratios` resource. Read that resource, present the
          options to the user, and pass their choice as `aspect_ratio`.
          Do NOT guess or pick a default on your own.

        TWO-PHASE CONFIRMATION (REQUIRED):
          1. Call WITHOUT `confirm` → returns a `preview` showing the TOTAL
             cost for all `n` frames. Show that cost to the user verbatim
             and ask: "You are going to spend X credits to generate N frame
             candidates. Proceed?".
          2. Only AFTER the user agrees, re-call with `confirm=True` to
             actually generate the frames.

        Defaults: `n=3`, model `fal-ai/nano-banana-pro`.
        Returns on success:
          {
            ok: true,
            frames: [
              { index: 0, imageUrl, generationId },
              ...
            ],
            count, creditsCharged, creditsRemaining
          }

        On partial failure (some frames fail), `frames` contains only the
        successes and `partial: true` is set with a `failed` count.
        """
        if not aspect_ratio or ":" not in aspect_ratio:
            return {
                "ok": False,
                "error": "aspect_ratio_required",
                "message": (
                    "You must ask the user which aspect ratio they want. Read "
                    "`studio://options/image-aspect-ratios` for the list of "
                    "available options, present them to the user, and pass "
                    "their choice as `aspect_ratio` (e.g. \"16:9\")."
                ),
            }
        if n < 1 or n > 6:
            return {
                "ok": False,
                "error": "usage",
                "message": "`n` must be between 1 and 6 frame candidates.",
            }
        
        # Clean up empty strings that should be None (LLM sometimes passes empty strings instead of omitting)
        if negative_prompt == "":
            negative_prompt = None
        if seed == "":
            seed = None
        if model == "":
            model = None
        
        resolved_model = model or "fal-ai/nano-banana-pro"

        import structlog
        log = structlog.get_logger(__name__)
        log.info("studio_storyboard_frames_model_used", model=resolved_model, n=n)

        client = _client()
        try:
            director_metadata = _extract_director_metadata(directorRunId, directorEventId, directorToolName)
            single_payload = _drop_none({
                "prompt": prompt,
                "model": resolved_model,
                "aspect_ratio": aspect_ratio,
                "negative_prompt": negative_prompt,
                **director_metadata,
            })

            if not confirm:
                # Preview: estimate one frame and multiply by n.
                try:
                    estimate = await client.estimate_pricing(single_payload)
                    per_credits = estimate.get("credits")
                    total_credits = (
                        per_credits * n if isinstance(per_credits, (int, float)) else None
                    )
                except WMStudioClientError as e:
                    log.warning(
                        "storyboard_preview_pricing_failed",
                        status=e.status_code,
                        message=str(e.message)[:200],
                    )
                    total_credits = None

                cost_blurb = (
                    f"~{total_credits} credits"
                    if total_credits is not None
                    else "an estimated cost (pricing unavailable)"
                )
                return {
                    "ok": True,
                    "preview": True,
                    "requiresConfirmation": True,
                    "operation": f"storyboard · {n}× {resolved_model}",
                    "framesRequested": n,
                    "estimatedCreditsTotal": total_credits,
                    "message": (
                        f"To generate {n} frame candidates I will spend {cost_blurb}. "
                        f"Confirm with the user before proceeding. If they accept, "
                        f"re-call this exact tool with `confirm=True`. After you have "
                        f"the frames, show every `imageUrl` to the user and ask which "
                        f"ONE to animate — then call `studio_generate_video` with that "
                        f"URL as `image_url`."
                    ),
                }

            # Confirmed: fan out N parallel image generations.
            async def _one(idx: int) -> dict[str, Any]:
                payload = dict(single_payload)
                # Seed each frame deterministically off the base seed so the
                # user can reproduce a specific candidate later.
                if seed is not None:
                    payload["seed"] = int(seed) + idx
                try:
                    res = await client.generate_image(payload)
                    # Queue-mode (CREATIVE_STUDIO_QUEUE_ENABLED) returns
                    # { queued: true, jobId, creditsCharged } and the URL
                    # only materializes after polling. Resolve here so the
                    # frame array always has a real imageUrl.
                    resolved = await _resolve_generation_response(client, res, kind="image", director_run_id=directorRunId)
                    return {"ok": True, "index": idx, "result": resolved}
                except InsufficientCreditsError as e:
                    return {"ok": False, "index": idx, "error": "insufficient_credits", "payload": e.payload}
                except WMStudioClientError as e:
                    log.warning(
                        "storyboard_frame_failed",
                        index=idx,
                        status=e.status_code,
                        message=str(e.message)[:200],
                    )
                    return {
                        "ok": False,
                        "index": idx,
                        "error": str(e.message),
                        "payload": e.payload,
                    }

            outcomes = await asyncio.gather(*[_one(i) for i in range(n)])

            # If the very first frame hit insufficient_credits, surface that
            # canonically and abort the rest are likely identical.
            first_credits_fail = next(
                (o for o in outcomes if not o["ok"] and o.get("error") == "insufficient_credits"),
                None,
            )
            if first_credits_fail and not any(o["ok"] for o in outcomes):
                return _upgrade_required(first_credits_fail.get("payload") or {})

            frames: list[dict[str, Any]] = []
            unresolved: list[dict[str, Any]] = []
            credits_charged = 0
            for o in outcomes:
                if not o["ok"]:
                    continue
                res = o["result"] if isinstance(o["result"], dict) else {}
                image_url = _extract_image_url(res)
                cc = res.get("creditsCharged")
                if isinstance(cc, (int, float)):
                    credits_charged += int(cc)
                if image_url:
                    frames.append({
                        "index": o["index"],
                        "imageUrl": image_url,
                        "generationId": res.get("generationId") or res.get("id"),
                        "jobId": res.get("jobId"),
                    })
                else:
                    # Charged but no URL surfaced (queue still pending or shape
                    # we don't know). Surface jobId so the user can recover.
                    unresolved.append({
                        "index": o["index"],
                        "jobId": res.get("jobId"),
                        "generationId": res.get("generationId") or res.get("id"),
                        "creditsCharged": cc,
                        "status": res.get("jobStatus") or res.get("status"),
                    })

            if not frames:
                return {
                    "ok": False,
                    "error": "all_frames_failed" if not unresolved else "frames_unresolved",
                    "creditsCharged": credits_charged,
                    "unresolvedFrames": unresolved,
                    "failures": [o for o in outcomes if not o["ok"]],
                    "message": (
                        f"None of the {n} frame generations returned a usable image URL. "
                        + (
                            f"{credits_charged} credits were already charged at queue submission. "
                            f"Use `studio_job_status` with each `jobId` below to recover the URLs "
                            f"once the jobs complete — do NOT call studio_storyboard_frames again "
                            f"or you'll be charged a second time."
                            if credits_charged > 0
                            else "No credits were charged."
                        )
                    ),
                }

            # Pull final balance once (cheaper than reading each per-frame response).
            response: dict[str, Any] = {
                "ok": True,
                "framesRequested": n,
                "count": len(frames),
                "frames": frames,
                "creditsCharged": credits_charged,
                "nextStep": (
                    "Show every imageUrl above to the user and ask which ONE to animate. "
                    "Then call studio_generate_video with that URL as `image_url` "
                    "(no `confirm`) to preview the video cost."
                ),
            }
            if len(frames) < n:
                response["partial"] = True
                response["failed"] = n - len(frames)
            structured = await _attach_credit_status(client, response)
            # Build structuredContent for MCP App viewer iframe
            sc_frames = [
                {
                    "index": f["index"],
                    "imageUrl": f["imageUrl"],
                    "generationId": f.get("generationId"),
                    "aspectRatio": aspect_ratio,
                }
                for f in frames
            ]
            # Download images for inline ImageContent blocks (native Claude rendering)
            image_urls = [f["imageUrl"] for f in frames]
            fetched = await asyncio.gather(*(_fetch_image_bytes(u) for u in image_urls))
            content_blocks: list[Any] = []
            for r in fetched:
                if r is not None:
                    data, mime = r
                    content_blocks.append(_image_content(data, mime))
            content_blocks.append(
                TextContent(type="text", text=f"{len(frames)} frames ready. Select one to animate.")
            )
            return CallToolResult(
                content=content_blocks,
                structuredContent={
                    "frames": sc_frames,
                    "count": len(frames),
                    "creditsCharged": credits_charged,
                    "creditsRemaining": structured.get("creditsRemaining"),
                },
            )
        finally:
            await client.aclose()

    # ---------- Video ----------

    @mcp.tool(
        name="studio_generate_video",
        meta={"ui": {"resourceUri": "ui://wmstudio/video-player"}},
    )
    async def studio_generate_video(
        prompt: str,
        confirm: bool = False,
        model: str = "bytedance/seedance-2.0-fast",
        image_url: str | None = None,
        aspect_ratio: str | None = None,
        duration: int | None = None,
        resolution: str | None = None,
        allow_text_to_video: bool = False,
        directorRunId: str | None = None,
        directorEventId: str | None = None,
        directorToolName: str | None = None,
    ) -> dict:
        """Generate a video from a chosen still frame (image-to-video).

        STORYBOARD-FIRST POLICY (HARD ENFORCED):
          You may NOT call this tool without an `image_url`. The required
          flow when the user asks for a video is:
            1. Call `studio_storyboard_frames(prompt, n=3)` to produce frame
               candidates.
            2. Show every returned `imageUrl` to the user and ask which ONE
               to animate.
            3. Call THIS tool with the chosen URL as `image_url` (no
               `confirm`) → returns a `preview` with `estimatedCredits`.
            4. Show that cost to the user, ask "Proceed?".
            5. Only AFTER the user agrees, re-call with `confirm=True` to
               actually generate the video.

          If the user EXPLICITLY says they want raw text-to-video and have
          opted out of storyboarding, pass `allow_text_to_video=True`. Do
          NOT set this on your own initiative; it must come from the user.

        Defaults to `bytedance/seedance-2.0-fast` (720p, ~5s).
        `duration` is seconds (model-dependent, typically 5–10).
        `resolution` is one of `480p | 720p | 1080p` (model-dependent;
        Seedance 2.0 Fast tops out at 720p).

        If `image_url` is provided it MUST be a real URL — either one
        returned by `studio_storyboard_frames` or one the user gave you.
        NEVER fabricate one.
        """
        # STORYBOARD-FIRST HARD GATE
        if not image_url and not allow_text_to_video:
            return {
                "ok": False,
                "error": "storyboard_required",
                "requiresStoryboard": True,
                "suggestedTool": "studio_storyboard_frames",
                "message": (
                    "Video generation requires a still frame to animate. Call "
                    "`studio_storyboard_frames(prompt=..., n=3)` first to generate "
                    "frame candidates, show every returned `imageUrl` to the user, "
                    "ask which ONE to animate, then re-call this tool with that "
                    "URL as `image_url`.\n\n"
                    "If — and only if — the user has explicitly asked you to skip "
                    "the storyboard step and go straight to text-to-video, re-call "
                    "this tool with `allow_text_to_video=True`."
                ),
            }

        gate = await _gate_asset_url(image_url, asset_kind="image", param="image_url", required=False)
        if gate:
            return gate
        client = _client()
        try:
            director_metadata = _extract_director_metadata(directorRunId, directorEventId, directorToolName)
            payload = _drop_none({
                "prompt": prompt,
                "model": model,
                "imageUrl": image_url,
                **director_metadata,
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
                    + (" · image-to-video" if image_url else " · text-to-video")
                ),
                resolve_kind="video",
                extra_structured=_drop_none({
                    "model": model,
                    "duration": duration,
                    "resolution": resolution,
                }),
                director_run_id=directorRunId,
            )
        finally:
            await client.aclose()

    @mcp.tool(name="studio_video_enhance")
    async def studio_video_enhance(
        video_url: str,
        upscale_factor: int = 2,
        target_fps: int | None = None,
        model: str = "fal-ai/topaz/upscale/video",
        directorRunId: str | None = None,
        directorEventId: str | None = None,
        directorToolName: str | None = None,
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
            director_metadata = _extract_director_metadata(directorRunId, directorEventId, directorToolName)
            payload = _drop_none({
                "model": model,
                "videoUrl": video_url,
                "upscale_factor": upscale_factor,
                "target_fps": target_fps,
                **director_metadata,
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
    async def studio_credits_balance(
        directorRunId: str | None = None,
        directorEventId: str | None = None,
        directorToolName: str | None = None,
    ) -> dict:
        """Return the authenticated user's credit balance.

        `{ balanceCredits, freeCredits, totalBalance, hasCredits }`.
        """
        client = _client()
        try:
            return await client.credits_balance(director_run_id=directorRunId)
        finally:
            await client.aclose()

    # Silence unused-warning for tools that lint-tooling sometimes flags.
    _ = (
        studio_generate_image,
        studio_upscale_image,
        studio_casting,
        studio_storyboard_frames,
        studio_generate_video,
        studio_video_enhance,
        studio_job_status,
        studio_web_search,
        studio_credits_balance,
        _safe_call,
    )
