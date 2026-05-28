"""Director production brief tools.

Two MCP tools the Director agent uses to maintain a long-lived "production
brief" per run — a structured document with logline, creative brief, script,
characters, locations, props, visual language, continuity rules, decisions,
and open questions. The brief is loaded into the system prompt every turn so
the agent stays consistent frame-to-frame.

Auth model:
    The brief endpoint accepts ``directorRunId`` in the body for agent
    requests; the wmstudio API resolves the user via the run and bypasses RLS
    via a service-role client (same pattern as references / generate-image /
    generate-video).
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_request

from src.config import get_settings
from src.tools.studio import _extract_director_metadata

log = structlog.get_logger(__name__)


def _wmstudio_base_url() -> str:
    settings = get_settings()
    return settings.wmstudio_api_url.rstrip("/")


async def _http_request(
    method: str,
    path: str,
    *,
    json: dict[str, Any] | None = None,
    params: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Issue an unauthenticated HTTP call to the wmstudio API.

    Director runs authenticate via ``directorRunId`` (query for GET, body for
    PATCH), so we never forward the user's bearer token here. Keeps this
    transport thin.
    """
    url = f"{_wmstudio_base_url()}{path}"
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        resp = await client.request(method, url, json=json, params=params, headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "mcp-director/brief-tools",
        })
    if resp.status_code >= 400:
        log.warn("director_brief_http_error", method=method, path=path, status=resp.status_code, body=(resp.text or "")[:400])
        return {"error": f"HTTP {resp.status_code}", "detail": (resp.text or "").strip()[:400]}
    try:
        return resp.json()
    except Exception:  # noqa: BLE001
        return {"error": "Invalid JSON response from wmstudio"}


def _resolve_run_id(directorRunId: str | None, directorEventId: str | None = None, directorToolName: str | None = None) -> str | None:
    """Always pull from FastMCP request state — ignore explicit kwarg since agent may fabricate wrong values."""
    try:
        request = get_http_request()
        meta = _extract_director_metadata(directorRunId, directorEventId, directorToolName)
        run_id = meta.get("directorRunId")
        if isinstance(run_id, str) and run_id and run_id != "run_current":
            return run_id
        # Fallback to request.state directly.
        state_run_id = getattr(request.state, "director_run_id", None)
        if isinstance(state_run_id, str) and state_run_id and state_run_id != "run_current":
            return state_run_id
    except Exception as exc:  # noqa: BLE001
        log.info("brief_resolve_run_id_state_failed", error=str(exc))
    return None


def register(mcp: FastMCP) -> None:
    """Register director brief tools."""

    @mcp.tool(name="director_brief_read")
    async def director_brief_read(
        directorRunId: str | None = None,
        directorEventId: str | None = None,
        directorToolName: str | None = None,
    ) -> dict[str, Any]:
        """Read the current production brief for this conversation.

        The brief is a long-lived structured document containing the creative
        direction for this run (logline, creative brief, script, characters,
        locations, props, visual language, audio, continuity rules, decisions,
        open questions). Read it before any visual generation to keep
        consistency.

        Returns a dict with `brief` containing `version`, `sections`, and
        `summary`. If no brief exists yet, an empty one is returned.
        """
        run_id = _resolve_run_id(directorRunId, directorEventId, directorToolName)
        if not run_id:
            return {"error": "No directorRunId in request — brief tools only work inside a Director run"}

        result = await _http_request(
            "GET",
            f"/api/director/{run_id}/brief",
            params={"directorRunId": run_id},
        )
        if "error" in result:
            return result
        return {"brief": result.get("brief")}

    @mcp.tool(name="director_brief_update")
    async def director_brief_update(
        sections: dict[str, Any] | None = None,
        summary: str | None = None,
        reason: str | None = None,
        directorRunId: str | None = None,
        directorEventId: str | None = None,
        directorToolName: str | None = None,
    ) -> dict[str, Any]:
        """Patch the production brief.

        Use this whenever the user gives you new creative direction you'll
        need to remember frame-to-frame.

        Args:
            sections: Partial sections to patch. Supported keys:
                - logline (str)
                - creativeBrief (str)
                - script (str)
                - characters (dict[str, str]) — merged by key
                - locations (dict[str, str]) — merged by key
                - props (dict[str, str]) — merged by key
                - visualLanguage (str)
                - audio (str)
                - continuity (str)
                - decisions (list[str]) — replaces, so include prior items
                - openQuestions (list[str]) — replaces, so include prior items
                For string sections, an empty string clears the section.
                For record sections, an empty value for a key removes that key.
            summary: Optional short TL;DR (<=1500 chars). Leave None to keep current.
            reason: Short rationale (<=500 chars) recorded on the audit revision.

        Returns the updated brief.
        """
        run_id = _resolve_run_id(directorRunId, directorEventId, directorToolName)
        if not run_id:
            return {"error": "No directorRunId in request — brief tools only work inside a Director run"}

        body: dict[str, Any] = {"directorRunId": run_id}
        if sections is not None:
            body["sections"] = sections
        if summary is not None:
            body["summary"] = summary
        if reason is not None:
            body["reason"] = reason

        result = await _http_request("PATCH", f"/api/director/{run_id}/brief", json=body)
        if "error" in result:
            return result
        return {"brief": result.get("brief")}
