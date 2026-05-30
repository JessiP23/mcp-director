"""End-to-end smoke for every studio_* MCP tool.

Two modes:

  --mode=mock   Uses respx to stand in for WM Studio and runs the in-process
                FastAPI app via TestClient. No deploy / network / auth needed.
                This proves every tool wires correctly: argument schema accepted,
                the right WM Studio endpoint hit, the right Authorization header
                forwarded (the upstream Supabase token, NOT the MCP JWT), and
                the JSON payload returned to the MCP client unchanged.

  --mode=live   Hits a real deployed mcp-director (Fly, Render, etc.) over the
                public Streamable-HTTP /mcp/ endpoint. You must provide:

                  --base-url   https://<your-fly-app>.fly.dev
                  --supabase-token <Supabase access JWT for the user under test>

                The script obtains an MCP access token by calling /oauth/token
                with the dev-only client credentials grant; on production
                deployments use --mcp-token <token> instead.

                In live mode every tool call hits the real WM Studio backend,
                charges real credits, and returns real fal.ai URLs. Use sparingly.

Usage:

    # Mock (default) — fast wiring proof, no creds needed
    PYTHONPATH=. python scripts/studio_smoke.py

    # Live, with credentials minted out of band
    PYTHONPATH=. python scripts/studio_smoke.py \\
        --mode=live \\
        --base-url=https://mcp-director.fly.dev \\
        --mcp-token="$MCP_TOKEN" \\
        --image-url=https://cdn.wmstudio.com/samples/cat.png \\
        --video-url=https://cdn.wmstudio.com/samples/clip.mp4 \\
        --skip studio_video_enhance studio_convert_to_3d
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any

# Defaults so importing src.* works without a real .env when in mock mode.
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "test-secret-do-not-use-in-prod-do-not-use")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("DIRECTOR_BASE_URL", "http://127.0.0.1:9420")
os.environ.setdefault("MCP_BASE_URL", "http://localhost:8080")


# ---------------------------------------------------------------------------
# Per-tool sample arguments. Tweak via CLI flags in live mode.
# ---------------------------------------------------------------------------

SAMPLE_PROMPT = (
    "a cinematic neon alley at dusk, moody volumetric lighting, 35mm film grain"
)


def build_samples(image_url: str, video_url: str, twin_id: str | None) -> list[dict[str, Any]]:
    return [
        {
            "name": "studio_credits_balance",
            "arguments": {},
            "needs": [],
        },
        {
            "name": "studio_generate_image",
            "arguments": {"prompt": SAMPLE_PROMPT, "aspect_ratio": "16:9"},
            "needs": [],
        },
        {
            "name": "studio_brandshot",
            "arguments": {
                "prompt": "lifestyle product hero on marble surface",
                "product_image_url": image_url,
                "brand_palette": ["#0a0a0a", "#f5f5f5", "#c79a52"],
                "aspect_ratio": "1:1",
            },
            "needs": ["image_url"],
        },
        {
            "name": "studio_casting",
            "arguments": {
                "character_name": "Ada",
                "prompt": "studio portrait, soft rembrandt lighting",
                "character_profile": {
                    "characterType": "human",
                    "genderIdentity": "female",
                    "raceEthnicity": "mixed",
                    "eyeColor": "hazel",
                    "hairStyle": "shoulder-length wavy",
                    "hairColor": "auburn",
                    "outfitStyle": "tailored beige trench",
                    "cinematicGenre": "noir",
                    "characterArchetype": "detective",
                },
            },
            "needs": [],
        },
        {
            "name": "studio_digital_twin",
            "arguments": {
                "prompt": "editorial portrait at golden hour, shallow DoF",
                **({"digital_twin_profile_id": twin_id} if twin_id else {}),
            },
            "needs": [],
        },
        {
            "name": "studio_ugc_room",
            "arguments": {
                "prompt": "candid product shelf shot, iphone vertical, natural light",
                "product_image_url": image_url,
                "room_style": "minimalist Brooklyn apartment",
                "aspect_ratio": "9:16",
            },
            "needs": ["image_url"],
        },
        {
            "name": "studio_upscale_image",
            "arguments": {"image_url": image_url, "upscale_factor": 2},
            "needs": ["image_url"],
        },
        {
            "name": "studio_convert_to_3d",
            "arguments": {"image_url": image_url},
            "needs": ["image_url"],
        },
        {
            "name": "studio_generate_video",
            "arguments": {
                "prompt": "drone push-in over a foggy mountain ridge at dawn",
                "aspect_ratio": "16:9",
                "duration": 5,
            },
            "needs": [],
        },
        {
            "name": "studio_video_enhance",
            "arguments": {"video_url": video_url, "upscale_factor": 2, "target_fps": 30},
            "needs": ["video_url"],
        },
        {
            "name": "studio_job_status",
            "arguments": {"job_id": "smoke-test-job-id"},
            "needs": [],
        },
    ]


# ---------------------------------------------------------------------------
# Streamable-HTTP helpers shared by both modes.
# ---------------------------------------------------------------------------


def _parse_sse_or_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("{"):
        return json.loads(text)
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            return json.loads(line[len("data:"):].strip())
    raise RuntimeError(f"Unparseable response: {text[:300]!r}")


@dataclass
class CallResult:
    name: str
    ok: bool
    elapsed_ms: int
    detail: str
    raw: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Mock mode — uses respx to stand in for the WM Studio Next.js API.
# ---------------------------------------------------------------------------


def run_mock(samples: list[dict[str, Any]]) -> list[CallResult]:
    import httpx
    import respx
    from fastapi.testclient import TestClient

    from src.auth import create_test_token, mcp_upstream_token_key
    from src.config import get_settings
    from src.middleware import auth_guard as guard_mod
    from src.server import root_app

    WMSTUDIO_BASE = "http://localhost:3000"
    UPSTREAM = "supabase-upstream-token-mock"

    os.environ["WMSTUDIO_API_URL"] = WMSTUDIO_BASE
    get_settings.cache_clear()

    token = create_test_token(user_id="smoke-user")
    upstream_key = mcp_upstream_token_key(token)

    # Inject fake redis with the upstream token for this MCP JWT.
    class _FakePipeline:
        def __init__(self) -> None:
            self._buf: list = []

        def zremrangebyscore(self, *_a, **_k):
            self._buf.append(0); return self
        def zcard(self, *_a, **_k):
            self._buf.append(0); return self
        def zadd(self, *_a, **_k):
            self._buf.append(1); return self
        def expire(self, *_a, **_k):
            self._buf.append(True); return self
        async def execute(self):
            out, self._buf = self._buf, []; return out

    class _FakeRedis:
        def __init__(self) -> None:
            self.kv = {upstream_key: UPSTREAM}
        async def get(self, k):
            return self.kv.get(k)
        async def sismember(self, _s, _v):
            return False
        def pipeline(self):
            return _FakePipeline()

    fake = _FakeRedis()
    guard_mod._redis_from_app_state = lambda _r: fake  # type: ignore[assignment]

    # Stub responses keyed by endpoint.
    def _img_response(req):
        body = json.loads(req.content.decode() or "{}")
        meta = body.get("metadata") or {}
        return httpx.Response(
            200,
            json={
                "success": True,
                "imageUrl": "https://cdn.wmstudio.test/img.png",
                "images": [{"url": "https://cdn.wmstudio.test/img.png"}],
                "generationId": "gen_mock",
                "requestId": "req_mock",
                "creditsCharged": 12,
                "_echo": {"toolId": meta.get("toolId"), "model": body.get("model")},
            },
        )

    def _video_response(_req):
        return httpx.Response(
            200,
            json={"success": True, "videoUrl": "https://cdn.wmstudio.test/v.mp4", "creditsCharged": 50},
        )

    def _upscale_video_response(_req):
        return httpx.Response(
            200,
            json={"success": True, "videoUrl": "https://cdn.wmstudio.test/v_upscaled.mp4", "creditsCharged": 80},
        )

    def _job_response(_req):
        return httpx.Response(
            200,
            json={"id": "smoke-test-job-id", "status": "completed", "progress": 100,
                  "resultUrl": "https://cdn.wmstudio.test/job.png"},
        )

    def _credits_response(_req):
        return httpx.Response(
            200,
            json={"balanceCredits": 1000, "freeCredits": 50, "totalBalance": 1050,
                  "hasCredits": True, "requiresCredits": False},
        )

    results: list[CallResult] = []

    with respx.mock(base_url=WMSTUDIO_BASE, assert_all_called=False) as mock:
        mock.post("/api/creative-studio/generate-image").mock(side_effect=_img_response)
        mock.post("/api/creative-studio/generate-video").mock(side_effect=_video_response)
        mock.post("/api/creative-studio/upscale-video").mock(side_effect=_upscale_video_response)
        mock.get("/api/jobs/smoke-test-job-id").mock(side_effect=_job_response)
        mock.get("/api/credits/balance").mock(side_effect=_credits_response)

        with TestClient(root_app) as client:
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            }
            init = client.post("/mcp/", headers=headers, json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                           "clientInfo": {"name": "smoke", "version": "0"}},
            })
            sid = init.headers["mcp-session-id"]
            sh = {**headers, "mcp-session-id": sid}
            client.post("/mcp/", headers=sh, json={"jsonrpc": "2.0", "method": "notifications/initialized"})

            for i, s in enumerate(samples, start=2):
                t0 = time.time()
                try:
                    r = client.post("/mcp/", headers=sh, json={
                        "jsonrpc": "2.0", "id": i, "method": "tools/call",
                        "params": {"name": s["name"], "arguments": s["arguments"]},
                    })
                    elapsed = int((time.time() - t0) * 1000)
                    if r.status_code != 200:
                        results.append(CallResult(s["name"], False, elapsed,
                                                  f"HTTP {r.status_code}: {r.text[:200]}"))
                        continue
                    body = _parse_sse_or_json(r.text)
                    if "error" in body:
                        results.append(CallResult(s["name"], False, elapsed,
                                                  f"jsonrpc error: {body['error']}", body))
                        continue
                    result = body.get("result") or {}
                    structured = result.get("structuredContent")
                    if structured is None and result.get("content"):
                        try:
                            structured = json.loads(result["content"][0].get("text", "{}"))
                        except Exception:
                            structured = None
                    detail = _summarize(structured)
                    results.append(CallResult(s["name"], True, elapsed, detail, structured))
                except Exception as e:  # noqa: BLE001
                    results.append(CallResult(
                        s["name"], False, int((time.time() - t0) * 1000), f"exception: {e}"))

    return results


# ---------------------------------------------------------------------------
# Live mode — hits a real deployed mcp-director.
# ---------------------------------------------------------------------------


def run_live(
    base_url: str,
    mcp_token: str,
    samples: list[dict[str, Any]],
    timeout: float,
) -> list[CallResult]:
    import httpx

    base_url = base_url.rstrip("/")
    if not mcp_token:
        raise SystemExit("--mcp-token is required for --mode=live")

    headers = {
        "Authorization": f"Bearer {mcp_token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }

    results: list[CallResult] = []
    with httpx.Client(base_url=base_url, timeout=httpx.Timeout(timeout, connect=10.0)) as client:
        init = client.post("/mcp/", headers=headers, json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                       "clientInfo": {"name": "studio-smoke", "version": "0.1"}},
        })
        if init.status_code != 200:
            raise SystemExit(f"initialize failed: HTTP {init.status_code}\n{init.text[:500]}")
        sid = init.headers.get("mcp-session-id", "")
        sh = {**headers, **({"mcp-session-id": sid} if sid else {})}
        client.post("/mcp/", headers=sh, json={"jsonrpc": "2.0", "method": "notifications/initialized"})

        for i, s in enumerate(samples, start=2):
            t0 = time.time()
            try:
                r = client.post("/mcp/", headers=sh, json={
                    "jsonrpc": "2.0", "id": i, "method": "tools/call",
                    "params": {"name": s["name"], "arguments": s["arguments"]},
                })
                elapsed = int((time.time() - t0) * 1000)
                if r.status_code != 200:
                    results.append(CallResult(s["name"], False, elapsed,
                                              f"HTTP {r.status_code}: {r.text[:200]}"))
                    continue
                body = _parse_sse_or_json(r.text)
                if "error" in body:
                    results.append(CallResult(s["name"], False, elapsed,
                                              f"jsonrpc error: {body['error']}", body))
                    continue
                result = body.get("result") or {}
                structured = result.get("structuredContent")
                if structured is None and result.get("content"):
                    try:
                        structured = json.loads(result["content"][0].get("text", "{}"))
                    except Exception:
                        structured = None
                results.append(CallResult(s["name"], True, elapsed,
                                          _summarize(structured), structured))
            except Exception as e:  # noqa: BLE001
                results.append(CallResult(s["name"], False, int((time.time() - t0) * 1000),
                                          f"exception: {e}"))
    return results


def _summarize(payload: Any) -> str:
    if not isinstance(payload, dict):
        return f"<{type(payload).__name__}>"
    keys = ("imageUrl", "videoUrl", "modelGlbUrl", "resultUrl", "totalBalance",
            "status", "generationId", "jobId", "ok", "error")
    bits: list[str] = []
    for k in keys:
        if k in payload:
            v = payload[k]
            if isinstance(v, str) and len(v) > 60:
                v = v[:57] + "..."
            bits.append(f"{k}={v}")
    return ", ".join(bits) or json.dumps(payload)[:140]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=["mock", "live"], default="mock")
    p.add_argument("--base-url", default="http://localhost:8080",
                   help="Public mcp-director base URL (live mode).")
    p.add_argument("--mcp-token", default=os.environ.get("MCP_TOKEN", ""),
                   help="MCP access token (live mode). Defaults to $MCP_TOKEN.")
    p.add_argument("--image-url", default="https://cdn.wmstudio.com/samples/sample.png",
                   help="Sample image URL for tools that need image input.")
    p.add_argument("--video-url", default="https://cdn.wmstudio.com/samples/sample.mp4",
                   help="Sample video URL for studio_video_enhance.")
    p.add_argument("--digital-twin-id", default=None,
                   help="Optional digital twin profile id for studio_digital_twin.")
    p.add_argument("--skip", nargs="*", default=[],
                   help="Tool names to skip (e.g. studio_video_enhance).")
    p.add_argument("--only", nargs="*", default=[],
                   help="If set, run only these tool names.")
    p.add_argument("--timeout", type=float, default=300.0,
                   help="HTTP timeout in seconds (live mode).")
    args = p.parse_args()

    samples = build_samples(args.image_url, args.video_url, args.digital_twin_id)
    if args.only:
        samples = [s for s in samples if s["name"] in set(args.only)]
    if args.skip:
        samples = [s for s in samples if s["name"] not in set(args.skip)]

    print("=" * 78)
    print(f"studio_smoke   mode={args.mode}   tools={len(samples)}"
          + (f"   base={args.base_url}" if args.mode == "live" else ""))
    print("=" * 78)

    if args.mode == "mock":
        results = run_mock(samples)
    else:
        results = run_live(args.base_url, args.mcp_token, samples, args.timeout)

    pass_n = sum(1 for r in results if r.ok)
    fail_n = len(results) - pass_n
    for r in results:
        flag = "OK " if r.ok else "FAIL"
        print(f"  [{flag}]  {r.name:28s}  {r.elapsed_ms:>5d}ms   {r.detail}")
    print("=" * 78)
    print(f"pass={pass_n}  fail={fail_n}  total={len(results)}")
    return 0 if fail_n == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
