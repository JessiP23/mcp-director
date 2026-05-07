# Director-cut discovery + production MCP setup

Use this when director-cut is a **Tauri app** with an **embedded/local API** and releases live on **GitHub**—not a separate cloud deployment.

---

## Confirmed: director-cut integration (your repo)

These facts match the **Tauri + embedded uvicorn** setup (`127.0.0.1` only, default port **9420**).

### Where the HTTP server lives

- **Rust** spawns Python: `uvicorn app.server:app --host 127.0.0.1 --port <backend_port>` (default **9420**).
- **No global `/api` prefix on the whole app** — REST routes are under `/api/...`. **MCP** (inside director-cut) is mounted at **`/mcp`**. Static exports under `/media/exports`.

### Two different “MCP” URLs (do not confuse)

| Entry point | URL (local) | Role |
|-------------|-------------|------|
| **director-cut** (embedded) | `http://127.0.0.1:9420/mcp` | Streamable HTTP MCP **inside** the desktop app’s FastAPI (Tauri/WebView can proxy here). |
| **director-mcp** (this repo) | `http://localhost:8080/mcp` (or your Fly URL) | **Hosted** MCP for Claude / Cursor / external clients; talks to director-cut via **`DIRECTOR_BASE_URL`** using REST (+ optional `POST …/mcp` JSON-RPC for LLM helpers). |

Clients like Claude connect to **director-mcp**, not to `9420/mcp`, unless you only use the desktop stack.

### Health checks (director-cut)

```bash
curl -sS http://127.0.0.1:9420/health
curl -sS http://127.0.0.1:9420/mcp/health
```

### Canonical `DIRECTOR_BASE_URL` (development)

```env
DIRECTOR_BASE_URL=http://127.0.0.1:9420
```

Use **`127.0.0.1`**, not `localhost`, to match the bound interface in the shipped path.

### Production / public API

- **Release pipeline:** GitHub Actions builds **desktop artifacts** (e.g. DMG) — **no** deployed long-running HTTP API in that path.
- The API exists **only while the app is running** and has started the backend on loopback — unless you add **Cloudflare Tunnel** or a **separately hosted** API.

### Auth alignment (important)

- director-cut **REST** (`/api/...`) expects **`Authorization: Bearer <token>`** verified against **Supabase** (and public paths for auth bootstrap — see director-cut `PUBLIC_PATH_EXACT`).
- **director-mcp** issues its **own** JWT after Supabase OAuth (`aud=director-mcp`). Tool calls currently forward **that** Bearer token to `DIRECTOR_BASE_URL` via `DirectorClient`.

**If director-cut rejects those calls**, you must either:

- forward the **Supabase access_token** from the OAuth callback for backend HTTP calls, or  
- teach director-cut to accept director-mcp’s JWT for `/api/*`, or  
- use a dedicated **desktop rotated token** path if you align with `MCP_INTEGRATION.md` on the director-cut side.

Resolve this **before** treating REST tool calls as production-ready.

### Getting a Supabase access token for local smoke (`DIRECTOR_BEARER_TOKEN`)

director-mcp’s **minted test JWT** is only for MCP auth. director-cut’s **`/api/*`** wants the **same Supabase session JWT** the desktop app uses (WM Studio validates that). You do not derive this from `JWT_SECRET`; you copy it from a logged-in session.

**What to copy:** the string field **`access_token`** from Supabase’s browser storage (a long `eyJ…` JWT). Not the refresh token, not the MCP token.

**Option A — Local Storage (fastest if the UI is WebView/Chromium)**

1. Run director-cut and **sign in** so the main screen loads.
2. Open **developer tools** (Tauri dev builds often expose this; some release builds hide it—in that case use a **dev build** or any **web** surface that uses the same Supabase project).
3. **Application** (Chrome) → **Local Storage** → pick your app origin (`http://127.0.0.1:…` or similar).
4. Look for a key like **`sb-<project-ref>-auth-token`** (Supabase JS v2). The value is JSON text.
5. Copy the **`access_token`** value inside that JSON (quoted string, starts with `eyJ`).

**Option B — Network tab**

1. DevTools → **Network**. Filter by **`user`** or **`auth`** or your Supabase host.
2. Trigger any API call that returns 200 (e.g. load projects).
3. Open a request to **`/rest/v1/`** or **`/auth/v1/`** and inspect **Request headers** → **`Authorization: Bearer eyJ…`**. Copy only the JWT after `Bearer `.

**Put it in director-mcp `.env` (development only)**

```env
ENVIRONMENT=development
DIRECTOR_BEARER_TOKEN=paste-eyJ...-here
```

Use the raw JWT only (no leading `Bearer `, no surrounding quotes — those are stripped if present). Restart `uvicorn`, then run the full smoke script (without `MCP_SMOKE_LIST_ONLY`). Tokens **expire** (commonly ~1 hour); refresh by signing in again and repeating the copy, or rely on **OAuth** through director-mcp so the Supabase token is stored in Redis at token exchange (no manual paste).

**Sanity-check the token hits director-cut**

```bash
TOKEN='paste-eyJ...'
curl -sS -o /dev/null -w "%{http_code}\n" \
  -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:9420/api/projects
```

You want **200** (or **401**/`detail` that is *not* “invalid token format”—meaning the server read it). **401 WM Studio** from this `curl` means the JWT is wrong or expired before you involve MCP.

### Integration block (copy into director-mcp `.env`)

```env
# director-mcp → director-cut (embedded FastAPI)
DIRECTOR_BASE_URL=http://127.0.0.1:9420
# Notes:
# - REST: Bearer token — must match what director-cut /api verifies (often Supabase JWT).
# - Local MCP URL on director-cut (different product): http://127.0.0.1:9420/mcp
# - Health: GET /health or GET /mcp/health on director-cut
# - Fly/hosted director-mcp cannot use 127.0.0.1 on your laptop: use a tunnel URL as DIRECTOR_BASE_URL while testing.
```

---

## Copy-paste: agent prompt for the director-cut repo

Give this to an agent (or run yourself) **in the director-cut repository** root. Goal: extract everything needed to wire `DIRECTOR_BASE_URL`, ports, auth, and whether a **public production API** exists at all.

```text
You are analyzing the "director-cut" codebase (Tauri + embedded backend). Answer concretely with file paths and quoted snippets.

1) **Where does the HTTP/API server start?**
   - Find the Rust side (tauri.conf, invoke handlers) and any sidecar (Node/Python/Rust) that binds a TCP port.
   - List the **default host, port, and path prefix** (e.g. http://127.0.0.1:9420, /api, /health).

2) **What is the canonical base URL for API clients in development?**
   - One line: DIRECTOR_BASE_URL=...

3) **Does a production/public API URL exist?**
   - Search for deployed backends (Fly, Railway, Vercel, worker URLs, env vars like API_URL, PUBLIC_URL).
   - If the app is desktop-only: state clearly "API only runs when the desktop app is open on localhost" and list evidence.

4) **Health and core routes**
   - Confirm paths for: health check, create run, list projects, auth header expected (Bearer JWT? Supabase?).

5) **GitHub Actions / release**
   - What do release artifacts build (desktop only vs also a server binary)?
   - Is there any workflow that deploys a long-running API we could set DIRECTOR_BASE_URL to?

6) **MCP / JSON-RPC on director-cut**
   - Is there POST /mcp or similar? Document method and body shape if present.

Output a short "Integration block" for another repo:

```env
# director-mcp / external clients
DIRECTOR_BASE_URL=...
# Notes: ...
```

```

---

## How this fits your case (Tauri, nothing “deploys” the API)

| Scenario | What `DIRECTOR_BASE_URL` is |
|----------|------------------------------|
| You + MCP **both on same computer**; Tauri **running** | `http://127.0.0.1:<port>` from discovery (often 9420 or similar). |
| **director-mcp on Fly.io**; API still only on your PC | You must expose the API with **Cloudflare Tunnel** (or host a real API). Fly cannot use `127.0.0.1` on your laptop. |
| You add a **hosted director API** later | `DIRECTOR_BASE_URL=https://api.yourproduct.com` from that deploy. |

**GitHub-hosted releases** are usually **installer/binaries**, not a URL for an HTTP API. So “prod URL for the Tauri app” for MCP purposes is either **tunnel → your machine while app runs**, or a **separate API service** you intentionally deploy.

---

## Test “like production” before Fly (fast feedback)

Do these **locally** in order; they catch most Fly failures in seconds.

1. **Same container as Fly**

   ```bash
   docker build -t director-mcp .
   docker run --rm -p 8080:8080 --env-file .env director-mcp
   ```

   Fix env/build issues here first.

2. **Contract check against director-cut**

   With Tauri running and backend up (default **9420**):

   ```bash
   curl -sS http://127.0.0.1:9420/health
   curl -sS http://127.0.0.1:9420/mcp/health
   ```

3. **Redis (Upstash)**

   Set `REDIS_URL=rediss://...` in `.env`. Start MCP; hit `/health`, then exercise one OAuth or one MCP call. Redis errors show up immediately in logs.

4. **Optional: production mode flags**

   ```bash
   ENVIRONMENT=production ENFORCE_HTTPS=false MCP_BASE_URL=http://localhost:8080 \
   docker run --rm -p 8080:8080 --env-file .env director-mcp
   ```

   (`ENFORCE_HTTPS=false` avoids TLS checks while still testing other prod paths; use real HTTPS + `ENFORCE_HTTPS=true` once behind TLS.)

---

## Deploy director-mcp “for free” and use Cloudflare Tunnel

### A. Hosted MCP (Fly) + API on your laptop (common while bootstrapping)

1. **Deploy MCP** to Fly (Dockerfile already in repo). Set secrets:

   - `REDIS_URL` (Upstash `rediss://...`)
   - `JWT_SECRET`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`
   - `MCP_BASE_URL=https://<your-app>.fly.dev`
   - `DIRECTOR_BASE_URL` = **tunnel URL** (step 2)

2. **Tunnel director-cut’s API** (laptop, Tauri running):

   - Install [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/).
   - Quick test: `cloudflared tunnel --url http://127.0.0.1:9420`  
     → note the `https://….trycloudflare.com` URL (temporary).
   - Stable: Cloudflare Zero Trust → Tunnels → configure hostname `director-api.yourdomain.com` → service `http://127.0.0.1:9420`.

3. Set **`DIRECTOR_BASE_URL`** on Fly to `https://director-api.yourdomain.com` (or trycloudflare URL for a short test).

4. **Supabase**: add redirect URL `https://<your-app>.fly.dev/oauth/callback` (and any dev URLs you use).

**Limitation:** Your PC must be on and Tauri running for the tunnel to work—that is not “serverless prod,” but it is real end-to-end prod *behavior* for demos.

### B. Everything on laptop + tunnel only MCP

If you don’t want Fly yet:

- Run MCP on `8080`, tunnel `cloudflared tunnel --url http://127.0.0.1:8080`.
- Set `MCP_BASE_URL` to the tunnel URL in `.env` / Supabase redirects.
- Keep `DIRECTOR_BASE_URL=http://127.0.0.1:9420` on the **same machine** (no Fly).

---

## Fly.io secret checklist (reference)

```bash
fly secrets set \
  REDIS_URL='rediss://...' \
  JWT_SECRET='...' \
  MCP_BASE_URL='https://<app>.fly.dev' \
  DIRECTOR_BASE_URL='https://<tunnel-or-hosted-api>' \
  SUPABASE_URL='https://xxx.supabase.co' \
  SUPABASE_ANON_KEY='...' \
  ENVIRONMENT=production
```

---

## Summary

- Use the **agent prompt** in director-cut to learn the real **port and routes**; that defines local `DIRECTOR_BASE_URL`.
- **GitHub releases** ≠ an API URL for MCP until you **tunnel** or **host** the API.
- **Before Fly:** `docker build` + `docker run` + curl health + Redis env.
- **With Fly:** tunnel the Tauri API to the public internet, set that URL as `DIRECTOR_BASE_URL` on Fly.
