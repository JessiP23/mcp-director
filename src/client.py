"""Async HTTP client for director-cut FastAPI backend."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

import httpx
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

log = structlog.get_logger(__name__)


class DirectorClientError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"{status_code}: {message}")


def _normalize_director_bearer_token(raw: str) -> str:
    """Strip wrapping quotes and accidental 'Bearer ' prefix from pasted .env tokens."""
    s = raw.strip()
    if len(s) >= 2 and ((s[0] == s[-1] == '"') or (s[0] == s[-1] == "'")):
        s = s[1:-1].strip()
    if s.lower().startswith("bearer "):
        s = s[7:].strip()
    return s


class DirectorClient:
    def __init__(self, base_url: str, user_token: str) -> None:
        self._base = base_url.rstrip("/")
        self._token = _normalize_director_bearer_token(user_token)
        self._client = httpx.AsyncClient(
            base_url=self._base,
            timeout=httpx.Timeout(30.0),
            headers={"Authorization": f"Bearer {self._token}"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def _raise_for_status(self, resp: httpx.Response, ctx: str) -> None:
        if resp.status_code >= 400:
            msg = resp.text[:500] if resp.text else resp.reason_phrase
            raise DirectorClientError(resp.status_code, f"{ctx}: {msg}")

    def _json_response(self, resp: httpx.Response, ctx: str) -> Any:
        """Parse JSON body; empty 2xx body becomes None. Non-JSON raises DirectorClientError."""
        self._raise_for_status(resp, ctx)
        raw = (resp.text or "").strip()
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            ctype = resp.headers.get("content-type", "")
            preview = raw[:160] + ("…" if len(raw) > 160 else "")
            raise DirectorClientError(
                resp.status_code,
                f"{ctx}: expected JSON but got {ctype!r}: {preview!r}",
            ) from e

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=0.5, max=8),
        retry=retry_if_exception_type(httpx.HTTPStatusError),
    )
    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        resp = await self._client.request(method, url, **kwargs)
        if resp.status_code in (429, 503):
            resp.raise_for_status()
        return resp

    async def health_check(self) -> bool:
        try:
            r = await self._client.get("/health")
            return r.status_code == 200
        except httpx.HTTPError as e:
            log.debug("health_check_failed", error=str(e))
            return False

    async def create_run(self, project_id: str, prompt: str, settings: dict) -> dict:
        payload = {"project_id": project_id, "prompt": prompt, "settings": settings}
        resp = await self._request("POST", "/api/runs", json=payload)
        data = self._json_response(resp, "create_run")
        assert isinstance(data, dict)
        return data

    async def cancel_run(self, run_id: str) -> dict:
        resp = await self._request("POST", f"/api/runs/{run_id}/cancel")
        if resp.status_code == 404:
            resp = await self._request("DELETE", f"/api/runs/{run_id}")
        if not resp.content:
            self._raise_for_status(resp, "cancel_run")
            return {"ok": True, "run_id": run_id}
        data = self._json_response(resp, "cancel_run")
        return data if isinstance(data, dict) else {"ok": True, "run_id": run_id}

    async def get_run(self, run_id: str) -> dict:
        resp = await self._request("GET", f"/api/runs/{run_id}")
        data = self._json_response(resp, "get_run")
        if data is None:
            raise DirectorClientError(resp.status_code, "get_run: empty response body")
        assert isinstance(data, dict)
        return data

    async def list_runs(self, project_id: str | None = None, limit: int = 20) -> list:
        params: dict[str, Any] = {"limit": limit}
        if project_id:
            params["project_id"] = project_id
        resp = await self._request("GET", "/api/runs", params=params)
        data = self._json_response(resp, "list_runs")
        if data is None:
            return []
        if isinstance(data, list):
            return data
        assert isinstance(data, dict)
        return data.get("runs", data.get("items", []))

    async def get_run_outputs(self, run_id: str) -> dict:
        resp = await self._request("GET", f"/api/runs/{run_id}/outputs")
        data = self._json_response(resp, "get_run_outputs")
        if data is None:
            return {}
        assert isinstance(data, dict)
        return data

    async def list_projects(self) -> list:
        resp = await self._request("GET", "/api/projects")
        data = self._json_response(resp, "list_projects")
        if data is None:
            return []
        if isinstance(data, list):
            return data
        assert isinstance(data, dict)
        return data.get("projects", data.get("items", []))

    async def create_project(self, name: str, description: str = "") -> dict:
        resp = await self._request(
            "POST",
            "/api/projects",
            json={"name": name, "description": description},
        )
        data = self._json_response(resp, "create_project")
        assert isinstance(data, dict)
        return data

    async def stream_events(self, run_id: str) -> AsyncIterator[dict]:
        token_q = quote(self._token, safe="")
        url = f"{self._base}/api/events/stream/{run_id}?access_token={token_q}"
        async with httpx.AsyncClient(timeout=httpx.Timeout(None)) as stream_client:
            async with stream_client.stream("GET", url) as resp:
                resp.raise_for_status()
                buffer = ""
                async for chunk in resp.aiter_text():
                    buffer += chunk
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if not line or line.startswith(":"):
                            continue
                        if line.startswith("data:"):
                            data = line[5:].strip()
                            if data == "[DONE]":
                                break
                            try:
                                yield json.loads(data)
                            except json.JSONDecodeError:
                                continue

    async def post_mcp_jsonrpc(
        self,
        method: str,
        params: dict | None = None,
    ) -> dict:
        """Call director-cut MCP bridge over HTTP JSON-RPC (tool/resource proxy)."""
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or {},
        }
        resp = await self._request("POST", "/mcp", json=body)
        payload = self._json_response(resp, "post_mcp_jsonrpc")
        if payload is None:
            raise DirectorClientError(resp.status_code, "post_mcp_jsonrpc: empty body")
        assert isinstance(payload, dict)
        if "error" in payload:
            err = payload["error"]
            raise DirectorClientError(int(err.get("code", -1)), str(err.get("message", err)))
        return payload.get("result", payload)

    async def get_settings_public(self) -> dict:
        resp = await self._request("GET", "/api/settings")
        if resp.status_code == 404:
            return {}
        data = self._json_response(resp, "get_settings")
        return data if isinstance(data, dict) else {}
