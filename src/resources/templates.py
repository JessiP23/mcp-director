"""Static and dynamic MCP resources + prompt templates."""

from __future__ import annotations

from fastmcp import Context
from fastmcp import FastMCP

from src.client import DirectorClient
from src.config import get_settings

STORYBOARD_VIEWER_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,sans-serif;background:#0a0a0a;color:#fff;padding:16px}
h3{font-size:12px;color:#666;margin-bottom:12px;letter-spacing:.08em;text-transform:uppercase}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
.frame{position:relative;border-radius:8px;overflow:hidden;cursor:pointer;border:2px solid transparent;transition:border-color .15s,transform .1s;aspect-ratio:var(--ar,16/9)}
.frame:hover{border-color:#444;transform:scale(1.01)}
.frame.selected{border-color:#7c3aed;box-shadow:0 0 0 1px #7c3aed}
.frame img{width:100%;height:100%;object-fit:cover;display:block}
.badge{position:absolute;bottom:6px;left:6px;background:rgba(0,0,0,.75);border-radius:4px;padding:2px 8px;font-size:11px;font-weight:600}
.check{position:absolute;top:6px;right:6px;background:#7c3aed;border-radius:50%;width:20px;height:20px;display:none;align-items:center;justify-content:center;font-size:10px}
.frame.selected .check{display:flex}
.btn{margin-top:14px;width:100%;padding:10px;background:#7c3aed;border:none;border-radius:8px;color:#fff;font-size:14px;font-weight:600;cursor:pointer;transition:opacity .15s}
.btn:disabled{opacity:.35;cursor:not-allowed}
.btn:hover:not(:disabled){opacity:.85}
.hint{margin-top:8px;text-align:center;font-size:11px;color:#555}
</style></head><body>
<h3>Choose a frame to animate</h3>
<div class="grid" id="grid"></div>
<button class="btn" id="btn" disabled>Animate this frame →</button>
<p class="hint" id="hint">Select a frame above</p>
<script>
(function(){var sel=null,frames=[];
function send(t){window.parent.postMessage({type:"prompt",text:t},"*");}
window.addEventListener("message",function(e){var d=e.data;if(d&&d.type==="toolResult"&&d.data){var r=d.data;frames=r.frames||[];var ar=(frames[0]&&frames[0].aspectRatio||"16:9").replace(":","/");document.documentElement.style.setProperty("--ar",ar);var g=document.getElementById("grid");g.innerHTML="";frames.forEach(function(f,i){var div=document.createElement("div");div.className="frame";div.innerHTML='<img src="'+f.imageUrl+'" loading="lazy"/><span class="badge">'+(i+1)+'</span><span class="check">✓</span>';div.onclick=function(){document.querySelectorAll(".frame").forEach(function(e){e.classList.remove("selected")});div.classList.add("selected");sel=f;document.getElementById("btn").disabled=false;document.getElementById("hint").textContent="Frame "+(i+1)+" selected";};g.appendChild(div);});}});
document.getElementById("btn").onclick=function(){if(!sel)return;document.getElementById("hint").textContent="Sending…";document.getElementById("btn").disabled=true;send("Animate frame "+(frames.indexOf(sel)+1)+": "+sel.imageUrl);};
})();</script></body></html>"""

VIDEO_PLAYER_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#000;font-family:system-ui,sans-serif;border-radius:10px;overflow:hidden}
video{width:100%;display:block;max-height:480px;background:#000}
.meta{display:flex;flex-wrap:wrap;gap:12px;padding:10px 14px;background:#0d0d0d;font-size:12px;color:#555}
.meta span b{color:#aaa}
.actions{display:flex;gap:8px;padding:10px 14px;background:#0d0d0d;border-top:1px solid #1a1a1a}
.dl{flex:1;text-align:center;padding:7px 12px;background:#1a1a1a;color:#7c3aed;font-size:13px;font-weight:600;text-decoration:none;border-radius:6px;border:none;cursor:pointer}
.dl:hover{background:#222}
.retry{flex:1;text-align:center;padding:7px 12px;background:#1a1a1a;color:#888;font-size:13px;font-weight:600;border-radius:6px;border:none;cursor:pointer}
.retry:hover{background:#222;color:#fff}
</style></head><body>
<video id="v" controls autoplay muted loop playsinline></video>
<div class="meta" id="meta"></div>
<div class="actions">
  <a class="dl" id="dl" href="#" download="video.mp4">⬇ Download</a>
  <button class="retry" id="retry">↩ Try different frame</button>
</div>
<script>
(function(){function send(t){window.parent.postMessage({type:"prompt",text:t},"*");}
window.addEventListener("message",function(e){var d=e.data;if(d&&d.type==="toolResult"&&d.data){var r=d.data;var url=r.videoUrl||r.url||"";document.getElementById("v").src=url;document.getElementById("dl").href=url;document.getElementById("meta").innerHTML="<span><b>Model</b> "+(r.model||"—")+"</span><span><b>Duration</b> "+(r.duration||"—")+"s</span><span><b>Resolution</b> "+(r.resolution||"—")+"</span><span><b>Credits used</b> "+(r.creditsCharged||"—")+"</span><span><b>Remaining</b> "+(r.creditsRemaining||"—")+"</span>";}});
document.getElementById("retry").onclick=function(){send("I want to pick a different frame");};
})();</script></body></html>"""


def register_resources(mcp: FastMCP) -> None:
    @mcp.resource(
        "ui://wmstudio/storyboard-viewer",
        mime_type="text/html;profile=mcp-app",
        meta={"csp": {"img-src": ["https://*"], "default-src": ["'self'", "'unsafe-inline'"]}},
    )
    def storyboard_viewer() -> str:
        """MCP App frame picker — renders storyboard frames as a clickable grid."""
        return STORYBOARD_VIEWER_HTML

    @mcp.resource(
        "ui://wmstudio/video-player",
        mime_type="text/html;profile=mcp-app",
        meta={"csp": {"media-src": ["https://*"], "default-src": ["'self'", "'unsafe-inline'"]}},
    )
    def video_player() -> str:
        """MCP App video player — renders generated video with metadata and controls."""
        return VIDEO_PLAYER_HTML

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

    @mcp.prompt("director://prompts/video-workflow")
    def video_workflow_prompt() -> list:
        """Mandatory 9-step workflow for ANY video request via studio_* tools.

        Agents should load this prompt at session start (or whenever the
        user asks for a video) to make the storyboard-first policy explicit
        in context. The studio_generate_video tool also enforces the policy
        at the tool layer (returns `storyboard_required` if no `image_url`),
        but having the policy in a prompt prevents the wasted tool call.
        """
        return [
            {
                "role": "system",
                "content": """
You are a video production agent powered by WM Studio. You generate videos through a
structured storyboard-first workflow. Videos and frames render inline in this chat —
never output raw URLs as the primary result, never use markdown image syntax for
frames or video. The MCP App viewer handles all visual rendering automatically.

════════════════════════════════════════════════════
WORKFLOW — FOLLOW THIS ORDER EXACTLY, EVERY TIME
════════════════════════════════════════════════════

[STEP 1] ASK FOR ASPECT RATIO — REQUIRED FIRST
Ask the user before doing anything else:
"What aspect ratio would you like?
  • 16:9 — Landscape (YouTube, desktop)
  • 9:16 — Vertical (TikTok, Reels, Shorts)
  • 1:1  — Square (Instagram feed)
  • 4:5  — Portrait (Instagram)"
Do not call any tool until you have their answer.

[STEP 2] STORYBOARD COST PREVIEW — NO CONFIRM
Call studio_storyboard_frames with:
  prompt      = <user's prompt>
  aspect_ratio = <chosen>
  n           = 3
  confirm     = false   ← DO NOT set true yet
This returns a cost preview only. Do not say frames are generating.

[STEP 3] SHOW COST + GET APPROVAL
Show the user the exact estimatedCredits from the preview response.
Say: "Generating 3 frame candidates will cost [X] credits. Proceed?"
Wait for explicit confirmation. Do not continue until they say yes.

[STEP 4] GENERATE FRAMES — WITH CONFIRM
Call studio_storyboard_frames with the exact same parameters plus:
  confirm = true
On success the tool returns structuredContent.frames[].
The MCP App viewer will render the 3 frames as a visual grid inline in the chat
automatically — you do not need to output image links or URLs.
After the viewer renders, say:
"Here are your 3 frame options — click one in the viewer above, then hit
'Animate this frame' to continue, or tell me a number (1, 2, or 3)."

[STEP 5] WAIT FOR FRAME SELECTION
Wait until the user either:
  a) Clicks a frame in the inline viewer (sends "Animate frame N: <url>")
  b) Types their choice ("1", "2", "3", or describes the frame)
Map their choice to the correct imageUrl from structuredContent.frames.
Never fabricate or guess a URL.

[STEP 6] VIDEO COST PREVIEW — NO CONFIRM
Call studio_generate_video with:
  prompt    = <same prompt>
  image_url = <chosen imageUrl from Step 5>
  confirm   = false   ← DO NOT set true yet
Do not say the video is generating.

[STEP 7] SHOW VIDEO COST + GET APPROVAL
Show the exact estimatedCredits from the preview response.
Say: "Generating the video will cost [X] credits. Proceed?"
Wait for explicit confirmation.

[STEP 8] GENERATE VIDEO — WITH CONFIRM
Call studio_generate_video with the exact same parameters plus:
  confirm = true
On success the tool returns structuredContent.videoUrl.
The MCP App video player will render the video inline automatically.

[STEP 9] CONFIRM COMPLETION
After the inline player renders, say:
"Your video is ready — playing above.
  Model: [model] | Duration: [Xs] | Resolution: [res]
  Credits used: [X] | Remaining: [X]"
Then offer next steps.

════════════════════════════════════════════════════
HARD RULES
════════════════════════════════════════════════════
- STORYBOARD FIRST, ALWAYS. Never call studio_generate_video without an image_url
  unless user explicitly says "skip storyboard" → then use allow_text_to_video=True.
- ALWAYS PREVIEW BEFORE CHARGING. Always call confirm=false first, show cost, wait.
- NEVER FABRICATE DATA. No invented URLs, IDs, credit amounts, or frame counts.
- INLINE RENDERING ONLY. Never output raw video URLs or markdown image links.
  The MCP App viewer renders everything inline. Trust it.
- PRESERVE CONTEXT. Keep prompt, aspect_ratio, and imageUrl consistent.
  If the user changes the prompt mid-workflow, restart from Step 2.
- CREDITS TRANSPARENCY. Show creditsCharged and creditsRemaining after each
  confirmed generation. If creditsRemaining < 10, warn the user.
- TOOL ERRORS. Report exact error, do not retry silently. On timeout: offer to
  check status. On partial:true: work with what succeeded, report what failed.
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
