# director-mcp

Hosted **Model Context Protocol** server for the **director-cut** AI video pipeline. External clients (Claude, Cursor, Claude Code, etc.) connect over **Streamable HTTP** (`/mcp`) with **OAuth 2.1 + PKCE**, backed by **Redis** for OAuth state, jobs, and rate limiting.

## Quick start (Claude.ai)

1. Open Claude.ai → Settings → Connectors  
2. Add custom connector: `https://<your-fly-app>.fly.dev/mcp/` — use your **`MCP_BASE_URL`** + **`/mcp/`** (trailing slash avoids redirect issues on some clients).  
3. Complete OAuth in the browser (via Supabase IdP)  
4. Example: “Create a 60-second product launch video for …”

**Tauri + Fly:** Claude talks to **Fly**, not to `127.0.0.1:9420`. Your desktop app must still run (with a **tunnel** to 9420) if **`DIRECTOR_BASE_URL`** on Fly points at that tunnel. See **[docs/director-cut-discovery-and-prod-setup.md](docs/director-cut-discovery-and-prod-setup.md)** — sections *Phased deploy* and *agent prompt — Tauri + hosted director-mcp*.

## Quick start (Claude Code)

```json
{
  "mcpServers": {
    "director": {
      "url": "https://<your-fly-app>.fly.dev/mcp/",
      "auth": "oauth"
    }
  }
}
```

## Architecture

- **`/`** — FastAPI: OAuth metadata, authorize/token/register, health, webhooks  
- **`/mcp`** — FastMCP Streamable HTTP (this app’s **public** MCP for Claude / Cursor)  
- **Director-cut** (Tauri) — Embedded uvicorn on **`http://127.0.0.1:9420`** by default; REST under `/api/*`, plus a **separate** local MCP at **`http://127.0.0.1:9420/mcp`** (desktop only).  
- **director-mcp** tools call `DIRECTOR_BASE_URL` (same machine: `http://127.0.0.1:9420`, or a **tunnel URL** when this server runs on Fly).

**Product context (WM Studio, Claude / Hermes / OpenClaw, Tauri):** **[docs/wm-studio-mcp-external-agents.md](docs/wm-studio-mcp-external-agents.md)**.

**Integration details, health paths, release vs tunnel, and auth alignment** (Supabase Bearer on director-cut REST vs director-mcp JWT): see **[docs/director-cut-discovery-and-prod-setup.md](docs/director-cut-discovery-and-prod-setup.md)**.

**OAuth on Fly + Supabase (`bad_oauth_state`, redirect allowlist, `MCP_BASE_URL`):** **[docs/oauth-fly-supabase-runbook.md](docs/oauth-fly-supabase-runbook.md)**.

## Environment

Copy `.env.example` → `.env` and set at minimum:

- `DIRECTOR_BASE_URL` — director-cut API base  
- `JWT_SECRET` — signing key for director-mcp access tokens (32+ random bytes in production)  
- `MCP_BASE_URL` — public URL of this service (OAuth redirects and metadata)  
- `SUPABASE_*` — same project as director-cut for the user login bridge  
- `REDIS_URL` — required in production for OAuth PKCE, jobs, rate limits  

## Local development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
docker compose up redis -d
PYTHONPATH=. uvicorn src.server:root_app --reload --host 0.0.0.0 --port 8080
```

Health:

```bash
curl http://localhost:8080/health
```

OAuth metadata:

```bash
curl http://localhost:8080/.well-known/oauth-authorization-server
curl http://localhost:8080/.well-known/oauth-protected-resource
```

MCP Inspector — use **Streamable HTTP** (this server is **not** STDIO):

1. Run: `npx @modelcontextprotocol/inspector`
2. Open the URL it prints (e.g. `http://localhost:6274/...`).
3. **Transport:** pick **Streamable HTTP** / **HTTP** (names vary by version). **Not** “stdio” / “command”.
4. **Server URL:** `http://localhost:8080/mcp/` — include the **trailing slash**. (A request to `/mcp` without it gets a **307** to `/mcp/`; some Streamable HTTP clients then drop the connection during `initialize`.)
5. **Auth:** director-mcp validates `Authorization: Bearer <JWT>`. There is no separate “JWT key” field in the Inspector — put the **full token** in a custom header:
   - Name: `Authorization`
   - Value: `Bearer eyJ...` (include the word `Bearer` and a space before the token)  
   Or use “Authentication → Bearer Token” if your Inspector build offers it and paste **only** the eyJ… part.
6. **JWT secret** lives in your **`.env`** as `JWT_SECRET` (used when you **mint** a token; the Inspector never needs the secret, only the minted JWT).

Mint a **dev JWT** (same secret as `.env`):

```bash
set -a && source .env && set +a
PYTHONPATH=. python -c "from src.auth import create_test_token; print(create_test_token())"
```

**Common mistake:** choosing STDIO and setting Command to `http://localhost:8080/mcp` — Node then tries to **execute** that string as a program (`spawn … ENOENT`). Use HTTP transport instead.

```bash
npx @modelcontextprotocol/inspector
```

Programmatic smoke test (`list_tools` + `director.project.list`):

```bash
PYTHONPATH=. .venv/bin/python scripts/smoke_mcp_tools.py
```

Tests and static checks:

```bash
PYTHONPATH=. pytest tests/ -v --tb=short
ruff check src/ tests/
mypy src/
```

## Tools (19)

### Pipeline — `director.run.*`, `director.project.*`

- `director.run.create` — start a run; optional wait/poll with progress  
- `director.run.status` / `director.run.outputs` / `director.run.cancel` / `director.run.list`  
- `director.project.create` / `director.project.list`  

### Creative — `director.creative.*`

- `director.creative.brief_to_run` — brief → settings (via director `/mcp` LLM when available) + run  
- `director.creative.batch_variations` — Cartesian variations, concurrent submits  
- `director.creative.remix` — remix from prior run outputs  
- `director.creative.storyboard_preview` / `director.creative.script_extract`  
- `director.creative.suggest_improvements` — LLM hints via `/mcp` with fallback  

### Assets — `director.asset.*`

- `director.asset.list` / `director.asset.download_url` / `director.asset.export_package`  

### Insights — `director.insight.*`

- `director.insight.run_cost` / `director.insight.pipeline_analytics` / `director.insight.model_recommendations`  

## Deploy (Fly.io)

```bash
fly launch --no-deploy
fly secrets set JWT_SECRET="$(openssl rand -base64 32)"
fly secrets set DIRECTOR_BASE_URL="https://your-director-api.example"
fly secrets set SUPABASE_URL="https://xxx.supabase.co"
fly secrets set SUPABASE_ANON_KEY="your-anon-key"
fly secrets set REDIS_URL="redis://..." 
fly secrets set MCP_BASE_URL="https://your-fly-app.fly.dev"
fly secrets set ENVIRONMENT="production"
fly deploy
```

Use the included `fly.toml` and `Dockerfile` (Uvicorn, 4 workers, `uvloop`).

## Deploy (Railway)

Repo includes `railway.json` with `Dockerfile` build and `/health` check. Set the same secrets as Fly via Railway variables.

## Security notes

- Production should use HTTPS (`ENVIRONMENT=production` or `ENFORCE_HTTPS=true` enforces `X-Forwarded-Proto: https` on OAuth and root middleware).  
- Do not log `Authorization` headers; use structured logging without raw tokens.  
- MCP JWTs use `aud=director-mcp` and optional Redis revocation set `mcp:tokens:revoked`.  

## Supabase OAuth bridge

`/oauth/authorize` stores PKCE state in Redis, redirects to Supabase `/auth/v1/authorize`, then `/oauth/callback` exchanges the Supabase code, mints a director-mcp JWT, and redirects to the client `redirect_uri` with an authorization `code`. `/oauth/token` completes PKCE and returns the MCP access token. Adjust Supabase token request body if your project uses a different grant/API version.


## command to run mcp inspector
npx @modelcontextprotocol/inspector http://localhost:8080/mcp

## Command to run the bakckend
- uvicorn src.server:root_app --host 0.0.0.0 --port 8080