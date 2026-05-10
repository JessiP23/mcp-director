# Cross-Repo Agent Prompt (director-cut)

Use this prompt in the `director-cut` repository so it aligns with this hosted MCP (`mcp-director`).

```text
You are working in the director-cut repository.

Goal:
Improve reliability and scalability for content generation requests coming from mcp-director.

Important integration contract:
- mcp-director sends Supabase Bearer tokens to DIRECTOR_BASE_URL.
- mcp-director tools call /api/* and may call /mcp JSON-RPC bridge paths.
- Keep response shapes backward compatible unless explicitly documented.

Tasks:
1) Verify and harden routes used by mcp-director:
   - /health
   - /api/projects/*
   - /api/runs/*
   - /api/runs/{id}/outputs
   - /mcp bridge (if enabled)
2) Ensure auth validation remains Supabase-user-token based (no service-role requirement from clients).
3) Add structured logs for run lifecycle:
   - request id, project id, run id, stage, elapsed ms, status class.
   - never log raw access tokens.
4) Ensure create-run and status polling are safe under retries:
   - clear 4xx vs 5xx,
   - bounded timeouts,
   - deterministic error payloads.
5) Confirm headless deployment instructions (no Tauri window required):
   - startup command,
   - required env vars,
   - health checks.
6) Add/refresh tests for:
   - auth-required routes,
   - run create/status/outputs happy path,
   - transient backend failures.

Deliverables:
- Minimal code changes with tests.
- Short docs update describing deployment + compatibility with mcp-director.
```
