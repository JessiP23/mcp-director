# OAuth on Fly + Supabase — audit, `bad_oauth_state`, operator runbook

For **director-mcp** (hosted MCP, e.g. `https://mcp-director.fly.dev`). Director-cut stays on `DIRECTOR_BASE_URL` (tunnel/API). Claude connects to **this** origin for MCP + OAuth.

---

## A. Code & config map

### A.1 OAuth routes (`src/auth.py`)

| Route | Role |
|--------|------|
| `GET /.well-known/oauth-authorization-server` | Metadata; `authorization_endpoint` = `{MCP_BASE_URL}/oauth/authorize`, `token_endpoint` = `{MCP_BASE_URL}/oauth/token`. |
| `GET /.well-known/oauth-protected-resource` | Resource = `{MCP_BASE_URL}/mcp`. |
| `GET /oauth/authorize` | Validates MCP client PKCE params; stores **`oauth:pkce:pending:{bridge}`** in Redis; redirects browser to **Supabase** `GET /auth/v1/authorize` with `redirect_to={MCP_BASE_URL}/oauth/callback` and `state={bridge}`. |
| `GET /oauth/callback` | **Must run on Fly.** Reads `code` + `state` (= bridge); loads Redis pending; exchanges `code` with Supabase `POST /auth/v1/token`; stores director code + Supabase access; redirects to **MCP client** `redirect_uri` with authorization `code` + original `state`. |
| `POST /oauth/token` | MCP client exchanges director code + `code_verifier` for director-mcp JWT; stores Supabase access in Redis under `mcp:upstream:…`. |
| `POST /oauth/register` | Dynamic client registration. |

### A.2 State / PKCE — no cookies

- **PKCE:** MCP client sends `code_challenge` (S256) to `/oauth/authorize`. Stored in Redis JSON under `oauth:pkce:pending:{bridge}` as `code_challenge`.
- **Client `state`:** Stored as `client_state` in same Redis blob; echoed back to client `redirect_uri` at the end.
- **Supabase `state`:** A random **`bridge`** (URL-safe token). Supabase returns it to **`/oauth/callback`**; used as Redis key. **Not stored in cookies.**
- **Cookie names / SameSite:** **None** — director-mcp does not set OAuth cookies for this flow.

### A.3 Supabase usage

- **Browser redirect:** `src/auth.py` builds  
  `{SUPABASE_URL}/auth/v1/authorize?provider=…&redirect_to=<URL-encoded MCP_BASE_URL/oauth/callback>&state=<bridge>`  
  Query params: **`provider`**, **`redirect_to`** (must be allowlisted in Supabase), **`state`** (bridge).
- **Token exchange:** `POST {SUPABASE_URL}/auth/v1/token?grant_type=authorization_code` with JSON `{"code": "<supabase code>"}` and headers `apikey`, `Content-Type`.

### A.4 `DIRECTOR_BASE_URL` (`src/client.py`, `src/tools/pipeline.py`, middleware)

- Read via **`get_settings().director_base_url`**.
- **`DirectorClient`** uses it as `httpx.AsyncClient(base_url=…)`; paths like **`/api/projects/`**, **`/api/runs/`**, **`/health`** (see `src/client.py`). **`follow_redirects=True`**, trailing slashes on collections.
- **Not used in OAuth.** OAuth completes entirely on **MCP_BASE_URL**.
- After OAuth, **`AuthGuardMiddleware`** pairs Supabase JWT in Redis; **`DirectorClient`** sends that Bearer to director-cut — not the MCP JWT alone.

### A.5 Fly secrets / env (typical)

| Variable | Used for |
|----------|----------|
| `MCP_BASE_URL` | OAuth URLs in metadata + `redirect_to` in Supabase authorize + `_ensure_https_production` “public” identity. **Must equal `https://mcp-director.fly.dev` (no path).** |
| `DIRECTOR_BASE_URL` | `DirectorClient` only — director-cut API base. |
| `SUPABASE_URL`, `SUPABASE_ANON_KEY` | Authorize redirect host + token exchange. |
| `JWT_SECRET` | Sign director-mcp access tokens. |
| `REDIS_URL` | PKCE pending, director codes, upstream token pairing, OAuth clients. |
| `ENVIRONMENT`, `ENFORCE_HTTPS` | Production HTTPS gate on OAuth + metadata. |

---

## B. Root-cause hypotheses for `bad_oauth_state` on wmstudio.io

| Hypothesis | Verdict |
|------------|---------|
| Callback never hits Fly; wrong redirect / client-only nav | **Plausible if `redirect_to` rejected** — Supabase falls back to **Site URL** (e.g. wmstudio.io) with error params User sees `wmstudio.io/...error=...` and **Fly logs show no `GET /oauth/callback`**. |
| Cookie not sent (SameSite / domain) | **Ruled out** for director-mcp OAuth — state lives in **Redis + Supabase `state` param**, not cookies. |
| Multiple OAuth attempts overwriting Redis | **Unlikely for wmstudio** — would usually yield **400 on Fly** (`unknown or expired state`) if callback **did** hit Fly. |
| `redirect_to` not allowlisted → Site URL fallback | **Most likely** — Supabase requires **`https://mcp-director.fly.dev/oauth/callback`** (exact or wildcard per project rules) under **Redirect URLs**. |
| `MCP_BASE_URL` mismatch vs Fly public URL | **Plausible** — wrong `redirect_to` string → same as above. |
| `X-Forwarded-Proto` breaking HTTPS guard | **Unlikely** — would **400 on Fly** before Supabase completes; Fly sets forwarded proto correctly. |

**Findings (one paragraph):**  
`bad_oauth_state` on **wmstudio.io** almost always means the browser finished the flow on Supabase’s **Site URL** (your web app), not on **`https://<fly-app>/oauth/callback`**. That happens when **`redirect_to` sent to `/auth/v1/authorize` is not allowed** in the Supabase project, so Supabase does not return the user to director-mcp; the WM Studio SPA then tries to interpret auth params it did not initiate → **`bad_oauth_state`**. Fix is **Supabase Dashboard redirect allowlist** + **`MCP_BASE_URL` on Fly exactly matching the public HTTPS origin**.

---

## C. Code changes (PR-style summary)

- **`src/auth.py`:** Structured **structlog** events: `oauth_authorize_start` (bridge hash prefix, `oauth_callback_url`, client redirect host), `oauth_callback_missing_params`, `oauth_callback_pending_hit` / `oauth_callback_pending_miss`, `supabase_token_exchange_failed` (truncated body), `oauth_callback_success_redirect`. No secrets or full tokens logged.
- **No cookie changes** — flow is Redis + query string only.
- **This doc** — operator checklist and Supabase/Google notes.

---

## D. Verification checklist

1. `curl -sS https://mcp-director.fly.dev/health` → **200** JSON.
2. `curl -sS "$DIRECTOR_BASE_URL/health"` → **200** when tunnel/API is up.
3. **Supabase → Authentication → URL configuration:**  
   - **Site URL** can stay wmstudio.io for the web app.  
   - **Redirect URLs** must include **exactly**  
     `https://mcp-director.fly.dev/oauth/callback`  
     (and/or wildcard `https://mcp-director.fly.dev/**` if your project allows it).  
4. **Google Cloud Console:** OAuth client **Authorized redirect URIs** include only  
   `https://<project-ref>.supabase.co/auth/v1/callback`  
   (not `fly.dev` — Supabase is the OAuth client to Google).
5. **Browser:** One tab; Connect from Claude; after Google, **address bar host** should be **`mcp-director.fly.dev`** on the callback step, then MCP client’s redirect URI — **not** wmstudio.io with `error=`.
6. **Fly logs** (`fly logs`): look for `oauth_callback_pending_hit` then `oauth_callback_success_redirect` on success.
7. **MCP:** `list_tools` / `director.project.list` with OAuth-issued token → **200** and data matching director-cut for the same Supabase user.

---

## E. Operator runbook (Jessi — 5 steps after deploy)

1. **Fly:** `fly secrets list` — confirm `MCP_BASE_URL=https://mcp-director.fly.dev`, `SUPABASE_*`, `REDIS_URL` (`rediss://`), `JWT_SECRET`, **`DIRECTOR_BASE_URL`** = current tunnel.  
2. **Supabase:** Add **`https://mcp-director.fly.dev/oauth/callback`** to **Redirect URLs**; save.  
3. **Redeploy** if you changed secrets: `fly deploy`.  
4. **Sanity:** `curl -sS https://mcp-director.fly.dev/health` and trigger **one** Connect in a **single** browser tab; watch **`fly logs`** for `oauth_authorize_start` (check logged `oauth_callback_url`) then `oauth_callback_pending_hit`.  
5. **Claude:** Complete connector; run one tool (e.g. list projects); if failure, grep logs for `oauth_callback_pending_miss` or `supabase_token_exchange_failed`.

---

## Related docs

- **[director-cut-discovery-and-prod-setup.md](./director-cut-discovery-and-prod-setup.md)** — Fly + tunnel phased deploy.  
- **[wm-studio-mcp-external-agents.md](./wm-studio-mcp-external-agents.md)** — Product architecture.
