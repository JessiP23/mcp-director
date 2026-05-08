#!/usr/bin/env python3
"""Smoke-test director-mcp over Streamable HTTP with a dev JWT.

Usage (from repo root):
  set -a && source .env && set +a
  PYTHONPATH=. .venv/bin/python scripts/smoke_mcp_tools.py

Optional:
  MCP_URL=http://localhost:8080/mcp/
  MCP_TEST_TOKEN=<paste jwt>   # else mints one via create_test_token()
  MCP_SMOKE_LIST_ONLY=1       # only initialize + list_tools (skip director-cut API call)

  Full smoke with a minted MCP JWT also needs a valid director-cut session: set
  DIRECTOR_BEARER_TOKEN in .env (development only) to your Supabase access JWT from
  the desktop app / browser, or use OAuth — the server then stores the upstream token
  in Redis when you exchange the authorization code.
"""

from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv

# Repo root on path
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

load_dotenv(os.path.join(_ROOT, ".env"))


async def main() -> None:
    from fastmcp import Client
    from fastmcp.exceptions import ToolError

    from src.auth import create_test_token

    token = os.environ.get("MCP_TEST_TOKEN") or create_test_token()
    url = os.environ.get("MCP_URL", "http://localhost:8080/mcp/")
    list_only = os.environ.get("MCP_SMOKE_LIST_ONLY", "").lower() in (
        "1",
        "true",
        "yes",
    )

    print(f"MCP URL: {url}")
    if list_only:
        print("Calling list_tools only (MCP_SMOKE_LIST_ONLY=1) …")
    else:
        print("Calling list_tools then director_project_list …")

    async with Client(url, auth=token) as client:
        tools = await client.list_tools()
        names = sorted(t.name for t in tools)
        print(f"tools ({len(names)}): {names[:8]}{' …' if len(names) > 8 else ''}")

        if list_only:
            print("OK: Streamable HTTP + JWT + Redis path works (no director-cut call).")
            return

        try:
            result = await client.call_tool("director_project_list", {})
        except ToolError as e:
            err = str(e)
            if "401" in err and "WM Studio" in err:
                print(
                    "\nThis is a director-cut session issue, not MCP. director-mcp is working.\n"
                    "You need the Supabase access_token (eyJ…) in DIRECTOR_BEARER_TOKEN for dev, "
                    "or complete OAuth so Redis stores it.\n"
                    "Step-by-step: docs/director-cut-discovery-and-prod-setup.md "
                    "(section «Getting a Supabase access token for local smoke»).\n"
                    "MCP-only check: MCP_SMOKE_LIST_ONLY=1 …\n"
                )
            raise
        print("director_project_list result:", result)


if __name__ == "__main__":
    asyncio.run(main())
