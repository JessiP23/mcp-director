# WM Studio · director-mcp · External agents (Claude, Hermes, OpenClaw)

This document states **why** director-mcp exists, **how** it fits WM Studio and the Tauri desktop stack, and **what** you must deploy and test so LLMs and agent runtimes can drive video and image generation inside an **agentic workflow**—without conflating local dev URLs with public MCP URLs.

---

## Purpose

**Goal:** Let **WM Studio** (web experience) and its **director-cut** backend power **third‑party LLMs and agents**—e.g. **Claude** (Claude.ai, Claude Code), **Hermes**, **OpenClaw**, and similar tools that speak the **Model Context Protocol (MCP)** over **HTTP**.

Those agents should be able to:

- Discover MCP **tools** (runs, projects, assets, creative helpers, etc.).
- Call those tools as part of a **multi-step workflow** (plan → generate → iterate).
- Effectively **create or advance video and image work** that lands in the same projects and runs WM Studio already uses, rather than only chatting in isolation.

**director-mcp** is the **hosted MCP server** that sits in front of director-cut: it exposes a **stable, internet‑reachable** MCP endpoint, **OAuth** for user identity, and **Redis** for session and rate limiting. It translates MCP tool calls into **authenticated HTTP** to director-cut’s REST (`/api/...`) and optional JSON-RPC bridges.

---

## How the pieces relate

| Piece | Role |
|--------|------|
| **WM Studio (web)** | Product UI; users sign in (e.g. Supabase). Same identity and project model as the backend. |
| **director-cut (Tauri + embedded FastAPI)** | Local **or** tunneled HTTP API (typical dev: `http://127.0.0.1:9420`). Hosts **`/api/*`** (runs, projects, assets, settings) and may expose a **local** MCP at `/mcp` **only while the app runs** on loopback. |
| **director-mcp (this repo)** | **Public MCP** for Claude and other MCP clients: **`https://<your-deploy>/mcp/`** (Streamable HTTP). Uses **OAuth 2.1 + PKCE** (Supabase as IdP bridge). Forwards tool traffic to **`DIRECTOR_BASE_URL`** with the user’s **Supabase access token** (paired in Redis after OAuth). |

**Important distinction:**

- **Claude / Hermes / OpenClaw** should be configured with the **deployed director-mcp URL** (e.g. Fly), **not** `127.0.0.1:9420`.
- **Tauri** continues to own the **local** developer experience: running the stack, tunneling when needed, and keeping the same API semantics WM Studio expects.

---

## End-to-end flow (agentic workflow)

1. **User** connects an MCP client (e.g. Claude connector) to **`https://<mcp-host>/mcp/`**.
2. **User** completes **OAuth**; director-mcp issues an **MCP access token** and stores the **Supabase `access_token`** in **Redis** keyed to that MCP token.
3. **Agent** calls MCP tools (`director_project_list`, `director_run_create`, asset tools, etc.).
4. **director-mcp** validates the MCP JWT, loads the paired Supabase token, and calls **`DIRECTOR_BASE_URL`** (e.g. Cloudflare tunnel → `127.0.0.1:9420` during laptop dev, or a future **always-on** API).
5. **director-cut** enforces WM Studio session rules (**WM Studio / Supabase JWT** on `/api/*`) and performs pipeline work; results appear in the same projects the user sees in WM Studio.

If **`DIRECTOR_BASE_URL`** is unreachable (tunnel down, Tauri closed, wrong URL), tools fail at the HTTP layer even when MCP and OAuth succeed.

---

## Deployment target (connect Claude and similar)

To **finish** the integration for external agents:

1. **director-mcp** is deployed (e.g. **Fly.io**) with a stable HTTPS origin  
   **`MCP_BASE_URL=https://<app>.fly.dev`**
2. **MCP endpoint for clients:**  
   **`https://<app>.fly.dev/mcp/`** (trailing slash avoids common redirect/client issues.)
3. **Secrets** on Fly: `REDIS_URL` (**`rediss://`** for Upstash), `JWT_SECRET`, `SUPABASE_*`, `ENVIRONMENT=production`, `ENFORCE_HTTPS=true`, and **`DIRECTOR_BASE_URL`** pointing at a **public** director-cut base (see below).
4. **Supabase** allows OAuth redirect  
   **`https://<app>.fly.dev/oauth/callback`** (and any IdP console steps Supabase documents).

**`DIRECTOR_BASE_URL` during Tauri-heavy development:**

- Often a **Cloudflare Tunnel** to `http://127.0.0.1:9420` while the desktop app runs.
- **Limitation:** Your machine and app must be available for tools to reach the API; this is acceptable for demos and early prod, not a substitute for a dedicated hosted API if you need 24/7 backend.

See **[director-cut-discovery-and-prod-setup.md](./director-cut-discovery-and-prod-setup.md)** for phased Fly + Cloudflare steps and the **Tauri orchestration agent prompt**.

---

## Configuring specific agent products

General pattern (MCP over **HTTP**, not stdio):

| Client | Typical configuration |
|--------|------------------------|
| **Claude.ai** | Custom connector / MCP URL: `https://<app>.fly.dev/mcp/`, then **OAuth** in browser. |
| **Claude Code** | Config: `url` → `https://<app>.fly.dev/mcp/`, `auth` → `oauth` where supported. |
| **Cursor** | MCP server entry with HTTP/SSE per product docs; same URL + OAuth or Bearer per your setup. |
| **Hermes / OpenClaw** | Whatever each product documents for **remote MCP** or **Streamable HTTP**; supply the same base MCP URL and complete OAuth if the client supports it, or Bearer if you mint tokens for testing only. |

Always prefer **OAuth** for real users so Supabase tokens are **paired in Redis** and refresh behavior matches your policy; avoid long‑lived manual **DIRECTOR_BEARER_TOKEN** outside development.

---

## Tauri / WM Studio dev “overall”

**Tauri completion** in this context means:

1. **Backend** (uvicorn on loopback) matches discovery: port, `/api/*`, `/health`, optional local `/mcp`.
2. **Auth** on `/api/*` stays aligned with **Supabase** so director-mcp forwarded tokens are accepted (already the intended production path after OAuth pairing).
3. **Tunnel** (or future hosted API) gives Fly a **`DIRECTOR_BASE_URL`** that returns **`GET /health`** from the public internet when the stack is up.
4. **Docs for users** (optional in-app): public MCP URL for Claude/agents; note that **laptop + tunnel** requires the app running for cloud agents to reach the API.

You do **not** need Tauri to “open a port” for Claude. Claude uses **Fly**. Tauri must only keep **director-cut** healthy for whatever **`DIRECTOR_BASE_URL`** you configured.

---

## Verification checklist (before saying “done”)

| Check | Pass criterion |
|--------|----------------|
| director-mcp | `GET https://<app>.fly.dev/health` |
| OAuth metadata | `GET /.well-known/oauth-authorization-server` |
| MCP transport | `MCP_SMOKE_LIST_ONLY=1` against `https://<app>.fly.dev/mcp/` with valid MCP auth |
| director-cut from Fly’s perspective | `GET https://<DIRECTOR_BASE_URL>/health` from internet while Tauri+tunnel up |
| Full tool | OAuth user calls e.g. `director_project_list`; lists match WM Studio projects |
| Claude | Connector completes OAuth; one natural language workflow creates or references a run/project |

---

## Summary

- **Purpose:** Connect **WM Studio / director-cut** capabilities to **Claude, Hermes, OpenClaw**, and other MCP agents so **video/image generation** fits **agentic** workflows.
- **director-mcp** is the **internet-facing MCP + OAuth** layer; **Tauri** remains the **desktop + local API** substrate.
- **Deploy** director-mcp on **Fly** (or equivalent), set **`MCP_BASE_URL`** and **`DIRECTOR_BASE_URL`** correctly, use **`/mcp/`** for clients, and keep **Supabase + Redis** production-ready.
- **“Tauri dev overall”** is complete when the **local API**, optional **tunnel**, and **agent connector** tests all pass with the same identity and project data WM Studio uses.

For commands and copy-paste prompts for the **director-cut** repo, use **[director-cut-discovery-and-prod-setup.md](./director-cut-discovery-and-prod-setup.md)**.
