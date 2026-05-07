# director-mcp

Hosted **Model Context Protocol** server for the **director-cut** AI video pipeline. External clients (Claude, Cursor, Claude Code, etc.) connect over **Streamable HTTP** (`/mcp`) with **OAuth 2.1 + PKCE**, backed by **Redis** for OAuth state, jobs, and rate limiting.

## Quick start (Claude.ai)

1. Open Claude.ai → Settings → Connectors  
2. Add custom connector: `https://your-domain.example/mcp` (your public `MCP_BASE_URL` + `/mcp`)  
3. Complete OAuth in the browser (via Supabase IdP)  
4. Example: “Create a 60-second product launch video for …”

## Quick start (Claude Code)

```json
{
  "mcpServers": {
    "director": {
      "url": "https://your-domain.example/mcp",
      "auth": "oauth"
    }
  }
}
```

## Architecture

- **`/`** — FastAPI: OAuth metadata, authorize/token/register, health, webhooks  
- **`/mcp`** — FastMCP Streamable HTTP (MCP 2025-06-18 transport)  
- **Director-cut** — All tools call your FastAPI at `DIRECTOR_BASE_URL` with the user’s Bearer token  

Configure `DIRECTOR_BASE_URL` to point at the machine where director-cut exposes `/api/*` and `/mcp`.

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

MCP Inspector:

```bash
npx @modelcontextprotocol/inspector http://localhost:8080/mcp
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
