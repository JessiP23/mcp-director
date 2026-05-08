"""Creative helpers and director client integration."""

from __future__ import annotations

import httpx
import pytest

from src.client import DirectorClient
from src.tools.creative import _parse_variation_dims, _slug_title


def test_parse_variation_dims_cartesian_input():
    d = _parse_variation_dims(["tone:serious,playful", "pacing:slow,fast"])
    assert d["tone"] == ["serious", "playful"]
    assert d["pacing"] == ["slow", "fast"]


def test_slug_title():
    assert "product" in _slug_title("Product Launch 2026 hero")


@pytest.mark.asyncio
async def test_mcp_llm_jsonrpc(mock_director, director_base_url):
    c = DirectorClient(director_base_url, "tok")
    try:
        r = await c.post_mcp_jsonrpc("tools/call", {"name": "director_service_llm"})
        assert r.get("structuredContent", {}).get("settings", {}).get("scene_count") == 5
    finally:
        await c.aclose()


@pytest.mark.asyncio
async def test_remix_run_end_to_end(respx_mock, director_base_url):
    respx_mock.get(f"{director_base_url}/api/runs/src").mock(
        return_value=httpx.Response(
            200,
            json={"id": "src", "project_id": "p9", "prompt": "original"},
        )
    )
    respx_mock.get(f"{director_base_url}/api/runs/src/outputs").mock(
        return_value=httpx.Response(200, json={"script": "A"})
    )
    respx_mock.post(f"{director_base_url}/api/runs/").mock(
        return_value=httpx.Response(201, json={"id": "run-remix", "status": "queued"}),
    )
    c = DirectorClient(director_base_url, "tok")
    try:
        source = await c.get_run("src")
        outputs = await c.get_run_outputs("src")
        merged = f"{source.get('prompt')}\n\nRemix: noir"
        r = await c.create_run(
            str(source["project_id"]),
            merged,
            {"remix_of": "src", "seed_checkpoint": outputs},
        )
        assert r["id"] == "run-remix"
    finally:
        await c.aclose()
