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
# Trailing slash avoids a 307 redirect; or use curl -L to follow redirects.
curl -sS -o /dev/null -w "%{http_code}\n" \
  -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:9420/api/projects/
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

## Copy-paste: agent prompt — Tauri + hosted director-mcp (orchestration)

Use this **in the director-cut (Tauri) repo** when you need an agent to **align the desktop app** with **director-mcp on Fly** and **Cloudflare Tunnel**. It complements the discovery prompt above (ports, routes).

```text
You are working in the director-cut repository (Tauri + embedded FastAPI on loopback).

## Architecture snapshot (do not conflate these three URLs)

1) **Tauri / embedded API** — Binds e.g. `http://127.0.0.1:9420`. The desktop UI and local integrations use `/api/*` and optionally local MCP at `http://127.0.0.1:9420/mcp` (Streamable HTTP). This only exists while the app is running.

2) **director-mcp (hosted)** — Example: `https://mcp-director.fly.dev`. External AI apps (Claude, Cursor, Claude Code) connect to **Streamable HTTP** at `https://mcp-director.fly.dev/mcp/` (trailing slash). Auth: **OAuth 2.1 + PKCE** via this service’s `/oauth/*` and Supabase as IdP. This is NOT stdio.

3) **Cloudflare Tunnel** — Public HTTPS URL forwarding to `http://127.0.0.1:9420` on the developer’s machine. director-mcp on Fly sets **DIRECTOR_BASE_URL** to this tunnel origin so **tools** (REST to `/api/...`) reach the same backend as the Tauri app. If the tunnel or Tauri app stops, hosted MCP tool calls fail.

## What “Tauri works with hosted MCP” actually means

- **Claude / Cursor** do **not** talk to `127.0.0.1:9420` directly. They talk to **director-mcp** on Fly.
- **Tauri** must still run (with backend on **9420**) **when** users rely on a **tunnel to laptop**, because Fly invokes tools against **DIRECTOR_BASE_URL** (the tunnel → localhost:9420).
- **No code change is strictly required** inside Tauri for Claude to use the product, unless you want:
  - In-app UI to show “Connect Claude” with the public MCP URL,
  - Or a user setting for “remote MCP base URL” for debugging,
  - Or documentation links / deep links.

If the product later offers a **always-on hosted director API**, replace the tunnel with that URL in director-mcp’s **DIRECTOR_BASE_URL**; Tauri may still be local-only for editing.

## director-mcp (Fly) env the other repo must respect

- **MCP_BASE_URL** = `https://<fly-app>.fly.dev` (HTTPS origin only, no `/mcp`).
- **DIRECTOR_BASE_URL** = tunnel origin `https://<something>.trycloudflare.com` or stable tunnel hostname → must return `GET /health` from the internet when Tauri is up.
- **REDIS_URL** = Upstash `rediss://...`
- **SUPABASE_*** = same project as director-cut; Supabase must allow redirect **`https://<fly-app>.fly.dev/oauth/callback`** (and any IdP settings Supabase documents).
- Production: **ENVIRONMENT=production**, **ENFORCE_HTTPS=true**; do not rely on **DIRECTOR_BEARER_TOKEN** (dev-only).

## director-cut checklist for compatibility

1) Confirm **default backend port** and binding (`127.0.0.1` vs `localhost`) match tunnel and director-mcp docs.
2) Confirm **REST** list routes use trailing slashes if FastAPI issues 307 (`/api/projects/` vs `/api/projects`) — clients should follow redirects or use canonical paths.
3) **Auth:** `/api/*` expects **Supabase session JWT** in `Authorization: Bearer`. director-mcp forwards the Supabase **access_token** stored in Redis after OAuth **or** dev **DIRECTOR_BEARER_TOKEN** — already implemented on director-mcp side; ensure director-cut does not reject valid Supabase JWTs from server-side calls.
4) Document for users: **Laptop + tunnel** = PC must stay on with app open for cloud tools to reach the API.

## Deliverables from this agent

1) Short **README section** or **MCP_INTEGRATION.md** update: “Using Claude / Cursor with hosted director-mcp” + public URL + note about tunnel + Tauri running.
2) Optional: env example or settings key for **PUBLIC_DIRECTOR_MCP_URL** (https://mcp-director.fly.dev) for in-app copy-paste only — no requirement to proxy MCP through Tauri.
3) List any **CORS / CSRF** concerns if the WebView ever calls director-mcp directly (usually unnecessary; prefer server-side or documented connector flow).

Output file paths changed and the exact user-facing URLs to document.
```

### Testing “MCP context” and Claude (Higgsfield-style)

**Hosted MCP** products expose an **HTTPS MCP URL** and **OAuth**, not a local port. Claude and similar apps connect **over the internet** to your server — same *class* of integration as other remote MCP hosts, as long as you configure **Streamable HTTP** (or whatever the product labels it) and **OAuth** per their UI.

| Goal | What to do |
|------|------------|
| **Verify director-mcp on Fly** | `curl -sS https://mcp-director.fly.dev/health` and `/.well-known/oauth-authorization-server` |
| **Verify MCP session + tools (no Claude yet)** | MCP Inspector: transport **HTTP / Streamable HTTP**, URL **`https://mcp-director.fly.dev/mcp/`**, auth via **Bearer** (minted JWT in dev) or step through **OAuth** if the Inspector supports it |
| **Smoke script** | `MCP_URL=https://mcp-director.fly.dev/mcp/` + env for OAuth token or dev JWT; `MCP_SMOKE_LIST_ONLY=1` first, then full tool call when **DIRECTOR_BASE_URL** tunnel is up |
| **Claude.ai** | Settings → Connectors → custom connector → MCP URL **`https://mcp-director.fly.dev/mcp`** (add trailing slash if their UI strips it wrong — prefer **`.../mcp/`** per README) → complete **OAuth** in browser (Supabase) |
| **Claude Code / Cursor** | Config: **`url`**: `https://mcp-director.fly.dev/mcp` or **`.../mcp/`**, **`auth`**: **`oauth`** where supported |

**Important:** Ports **8080** / **9420** are **local-only**. Claude never connects to `127.0.0.1`; it connects to **`https://mcp-director.fly.dev`**. **9420** is only for **Tauri + tunnel origin**.

---

## How this fits your case (Tauri, nothing “deploys” the API)

| Scenario | What `DIRECTOR_BASE_URL` is |
|----------|------------------------------|
| You + MCP **both on same computer**; Tauri **running** | `http://127.0.0.1:<port>` from discovery (often 9420 or similar). |
| **director-mcp on Fly.io**; API still only on your PC | You must expose the API with **Cloudflare Tunnel** (or host a real API). Fly cannot use `127.0.0.1` on your laptop. |
| You add a **hosted director API** later | `DIRECTOR_BASE_URL=https://api.yourproduct.com` from that deploy. |

**GitHub-hosted releases** are usually **installer/binaries**, not a URL for an HTTP API. So “prod URL for the Tauri app” for MCP purposes is either **tunnel → your machine while app runs**, or a **separate API service** you intentionally deploy.

### How auth works in production (vs your local smoke test)

| Piece | Local dev (what you just ran) | Production (`ENVIRONMENT=production`) |
|--------|--------------------------------|----------------------------------------|
| **MCP** (`/mcp/`) | Browser/Inspector/smoke sends **`Authorization: Bearer <director-mcp JWT>`** (minted via `create_test_token` or from **`/oauth/token`**) | Same: clients use OAuth; user ends up with an **MCP access token** after PKCE. |
| **director-cut** (`DIRECTOR_BASE_URL` /api) | **`DIRECTOR_BEARER_TOKEN`** in `.env` supplies the **Supabase** JWT so tools work without going through OAuth on every smoke run. | **`DIRECTOR_BEARER_TOKEN` is not used** (only read when `ENVIRONMENT=development`). After OAuth, the Supabase **`access_token`** from the callback is stored in **Redis** next to the MCP token; **`AuthGuard`** loads it for each request. Users never paste Supabase tokens into Fly secrets. |
| **Expiry** | You refresh **DIRECTOR_BEARER_TOKEN** manually when Supabase expires. | MCP JWT and cached Supabase token have TTLs; user **re-auths via OAuth** when the client refreshes. |

So: **manual Supabase token is a dev convenience, not the product design.** Deployed behavior is **OAuth → Redis pairing → tools forward Supabase to director-cut**.

### What to test before and after deploy (each part)

1. **This service only** — `GET /health`, `/.well-known/oauth-*`, then **`MCP_SMOKE_LIST_ONLY=1`** (no director-cut).
2. **Director-cut reachability from the host** — `curl` **`DIRECTOR_BASE_URL/health`** (from the same network as the MCP process: Fly cannot call **`127.0.0.1`** on your laptop unless you use a **tunnel**).
3. **Full path** — One **OAuth** sign-in, then an MCP tool that hits `/api/` (same as your successful **`director_project_list`**), or a staging secret user + automated E2E later.
4. **Never put a user’s Supabase JWT in Fly secrets** — only `JWT_SECRET`, Supabase **anon** key, `REDIS_URL`, URLs, etc.

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

## Phased deploy: Fly first, then Cloudflare, then wire URLs

You already have **Upstash** (`rediss://` URL) and **Supabase** (project URL + anon key). Install two CLIs on your machine: **[Fly](https://fly.io/docs/hands-on/install-flyctl/)** (`fly`) and **[cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/)**. Work each **group** to completion before moving on.

### Group 1 — Fly (finish this before Cloudflare)

1. **Log in**

   ```bash
   fly auth login
   ```

2. **App name** — In `fly.toml`, `app = "director-mcp"` must be unique on Fly. Change it if `fly launch` complains.

3. **First deploy** (from repo root):

   ```bash
   fly launch
   ```

   - Choose region, attach to this `Dockerfile`, decline extra Postgres unless you want it (you use Upstash for Redis).
   - After a successful deploy, note your URL: **`https://<app-name>.fly.dev`**.

4. **Smoke the app** (no secrets yet beyond what launch set):

   ```bash
   curl -sS "https://<app-name>.fly.dev/health"
   ```

   You want JSON `{"status":"ok",...}`. If this fails, fix Fly/DNS/build before anything else.

5. **Stop here for Group 1** — You now have a stable **`MCP_BASE_URL`** candidate:  
   **`https://<app-name>.fly.dev`** (no `/mcp` on the end for this variable).

### Group 2 — Cloudflare Tunnel (expose director-cut)

Fly cannot call `127.0.0.1:9420` on your laptop. After Fly works, expose the **director-cut API** with a **public HTTPS URL**.

1. **Run director-cut** locally so **`http://127.0.0.1:9420/health`** works.

2. **Quick tunnel** (ephemeral URL, good for first E2E test):

   ```bash
   cloudflared tunnel --url http://127.0.0.1:9420
   ```

   Copy **`https://….trycloudflare.com`** (new each run).

3. **Optional stable URL** — Cloudflare Zero Trust → **Networks → Tunnels** → create tunnel → public hostname (e.g. `director-api.yourdomain.com`) → service **`http://127.0.0.1:9420`**.

4. **Test from your phone or another network** (not only localhost):

   ```bash
   curl -sS "https://<tunnel-host>/health"
   ```

   If this fails, Fly will not be able to reach director-cut either.

5. **Stop here for Group 2** — Your **`DIRECTOR_BASE_URL`** is that origin only, e.g.  
   **`https://abc123.trycloudflare.com`** or **`https://director-api.yourdomain.com`** (no path).

**Limitation:** Laptop must be on and director-cut running while you use a tunnel to it.

### Group 3 — Supabase (URLs only; you already have the project)

1. In Supabase **Authentication → URL configuration**, allow your app’s origins/redirects as required by your setup.

2. Ensure OAuth can return to director-mcp:

   **`https://<app-name>.fly.dev/oauth/callback`**

   (Built from **`MCP_BASE_URL`** in your server.)

3. If Google/GitHub console requires redirect URIs for Supabase, follow Supabase’s docs for those (often Supabase hosts the IdP callback).

### Group 4 — Fly secrets + production flags

Set everything in **one** place on Fly (replace values):

```bash
fly secrets set \
  ENVIRONMENT=production \
  ENFORCE_HTTPS=true \
  REDIS_URL='rediss://...' \
  JWT_SECRET='<long-random-secret>' \
  MCP_BASE_URL='https://<app-name>.fly.dev' \
  DIRECTOR_BASE_URL='https://<tunnel-host-from-group-2>' \
  SUPABASE_URL='https://<ref>.supabase.co' \
  SUPABASE_ANON_KEY='eyJ...' \
  SUPABASE_OAUTH_PROVIDER=google
```

- Do **not** set **`DIRECTOR_BEARER_TOKEN`** in production (dev-only).
- Redeploy so machines pick up secrets:

  ```bash
  fly deploy
  ```

### Group 5 — Verify end-to-end

| Step | Command / action |
|------|-------------------|
| MCP health | `curl -sS https://<app>.fly.dev/health` |
| OAuth metadata | `curl -sS https://<app>.fly.dev/.well-known/oauth-authorization-server \| head` |
| Director via tunnel | `curl -sS https://<tunnel-host>/api/projects/` with a valid Bearer (or sign in via app) |
| MCP client | Streamable HTTP → **`https://<app>.fly.dev/mcp/`** + OAuth or issued token; call a tool |

---

### Alternative: MCP on laptop only (no Fly)

- Run MCP on port 8080 locally, tunnel **`cloudflared tunnel --url http://127.0.0.1:8080`**, set **`MCP_BASE_URL`** to that HTTPS URL, keep **`DIRECTOR_BASE_URL=http://127.0.0.1:9420`** on the **same** machine.

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
