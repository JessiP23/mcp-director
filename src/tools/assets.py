"""Asset-oriented tools."""

from __future__ import annotations

from fastmcp import Context
from fastmcp import FastMCP

from src.tools.pipeline import _user_client


def register(mcp: FastMCP) -> None:
    @mcp.tool(name="director_asset_list")
    async def list_assets(ctx: Context, run_id: str) -> list:
        """List all generated assets (images, audio, video clips) for a run."""
        _, client = _user_client(ctx)
        outputs = await client.get_run_outputs(run_id)
        assets = outputs.get("assets") or outputs.get("media") or outputs.get("files")
        if isinstance(assets, list):
            return assets
        if isinstance(assets, dict):
            return [{"name": k, **(v if isinstance(v, dict) else {"url": v})} for k, v in assets.items()]
        clips = outputs.get("clips", [])
        return clips if isinstance(clips, list) else []

    @mcp.tool(name="director_asset_download_url")
    async def get_download_url(ctx: Context, run_id: str, asset_name: str) -> dict:
        """Get a signed download URL for a specific asset from a run."""
        _, client = _user_client(ctx)
        outputs = await client.get_run_outputs(run_id)
        assets = await list_assets(ctx, run_id)
        for a in assets:
            name = str(a.get("name") or a.get("id") or "")
            if name == asset_name or asset_name in str(a.get("path", "")):
                return {
                    "run_id": run_id,
                    "asset_name": asset_name,
                    "url": a.get("url") or a.get("signed_url") or outputs.get("download", {}).get(asset_name),
                }
        return {"run_id": run_id, "asset_name": asset_name, "url": None, "error": "not_found"}

    @mcp.tool(name="director_asset_export_package")
    async def export_package(ctx: Context, run_id: str) -> dict:
        """
        Get the final export package info including master video URL,
        individual clip URLs, script PDF, and storyboard PDF.
        """
        _, client = _user_client(ctx)
        outputs = await client.get_run_outputs(run_id)
        pkg = outputs.get("export") or outputs.get("package")
        if isinstance(pkg, dict):
            return {"run_id": run_id, **pkg}
        return {
            "run_id": run_id,
            "master_video_url": outputs.get("master_video_url") or outputs.get("render_url"),
            "clips": outputs.get("clips", []),
            "script_pdf": outputs.get("script_pdf_url"),
            "storyboard_pdf": outputs.get("storyboard_pdf_url"),
            "raw_outputs_keys": list(outputs.keys()),
        }
