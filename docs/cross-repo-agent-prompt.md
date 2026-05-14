# Cross-Repo Agent Prompt (director-cut)

Paste this into a new agent chat **inside the `director-cut` repository**.

---

```text
You are working in the director-cut repository.
The deployed app is at https://director-cut.fly.dev

## Goal
Runs are created successfully then immediately fail with status="failed",
current_stage="intake" within 4 seconds. The pipeline never produces output.
Find the exact cause, fix it, and verify end-to-end content generation works.

---

## STEP 1 — Read fly logs to find the exact traceback

Run in your terminal:
  fly logs -a director-cut 2>&1 | head -200

Search for the string "run_failed" or "traceback" or "⚠️" or "ERROR".
The engine writes the error like this in engine.py:
  log.error("run_failed", run_id=run_id, error=str(exc))
  traceback.print_exc()
Copy the full traceback — it is the single most important clue.

---

## STEP 2 — Likely root causes (check in this order)

### 2a. DB pool not initialised / wrong schema

The intake node calls `record_step()` and `checkpoint()` which call `get_pool()`.
If `DATABASE_URL` is wrong, or the `run_steps` / `checkpoints` table does not
exist in Supabase, those writes raise an exception immediately.

Check:
  fly secrets list -a director-cut | grep DATABASE_URL
  # Confirm it is set and starts with postgresql://

Then SSH into the Fly machine and verify DB connectivity:
  fly ssh console -a director-cut
  python3 -c "
import asyncio, os, asyncpg
async def t():
    pool = await asyncpg.create_pool(os.environ['DATABASE_URL'])
    r = await pool.fetchval('SELECT 1')
    print('DB OK:', r)
    tables = await pool.fetch(\"SELECT tablename FROM pg_tables WHERE schemaname='public'\")
    print('Tables:', [r['tablename'] for r in tables])
asyncio.run(t())
"

If DB is OK but tables are missing, `init_db()` didn't run. Check the lifespan
function in server.py — it calls `await init_db()` at startup and will RAISE if
DATABASE_URL is unset. Look for "⚠️ Database init failed" in logs.

### 2b. run_steps schema mismatch

`record_step()` in base.py inserts with column `output_json`:
  INSERT INTO run_steps (id, run_id, stage, status, output_json, error, started_at)

But the CREATE TABLE in connection.py defines the column as `output_json` — confirm
Supabase has that column name exactly (not `output` or `result`).

If the table was created by an earlier version with a different column name,
asyncpg raises `UndefinedColumnError` and the run fails at the first `record_step`.

Fix: in Supabase SQL editor run:
  ALTER TABLE run_steps RENAME COLUMN output TO output_json;
  -- or if the column is just missing:
  ALTER TABLE run_steps ADD COLUMN IF NOT EXISTS output_json TEXT DEFAULT '{}';

### 2c. process_restart — run was "running" from a previous deploy

The lifespan startup code marks all runs with status='running' as failed and
inserts an error row with message='process_restart'. This is correct behaviour
for a fresh deploy. It means the PREVIOUS run (not your current test run) was
recycled. Not the bug you're seeing — but check with:

  curl -sS --http1.1 -H "Authorization: Bearer $TOKEN" \
    https://director-cut.fly.dev/api/runs/YOUR_RUN_ID/errors

After you deploy the GET /{run_id}/errors route (see Step 3).

### 2d. asyncio.create_task fails silently before the pipeline starts

In routes/runs.py:
  asyncio.create_task(start_run_async(run_id, body))

If the import of `start_run_async` raises (e.g. a missing dependency like groq /
fal), the `except Exception` block only prints a warning — the task is never
created. The run stays in intake with status='running' until the lifespan
recovery on the NEXT restart marks it 'failed'.

To check: search fly logs for "⚠️ Pipeline engine failed to start".

Fix: replace the bare `except Exception` print with a proper DB failure:
  try:
      from app.graph.engine import start_run_async
      asyncio.create_task(start_run_async(run_id, body))
  except Exception as e:
      import traceback, uuid as _u
      from datetime import datetime as _dt
      from app.db.connection import get_pool
      traceback.print_exc()
      pool = get_pool()
      now = _dt.utcnow().isoformat()
      await pool.execute(
          "UPDATE runs SET status='failed', updated_at=$1 WHERE id=$2", now, run_id
      )
      await pool.execute(
          "INSERT INTO errors (id, run_id, message, recoverable, created_at)"
          " VALUES ($1, $2, $3, 0, $4)",
          _u.uuid4().hex, run_id, f"engine_import_failed: {e}", now,
      )

### 2e. Missing API keys (GROQ_API_KEY / FAL_KEY)

The planning, script, and render nodes call Groq (LLM) and Fal (image/video).
If the key is missing or invalid the node raises — the engine catches it and
marks the run failed. These should appear in `errors` table.

Verify in Fly:
  fly secrets list -a director-cut
  # Confirm GROQ_API_KEY and FAL_KEY are present

Quick smoke test (from your machine):
  curl -sS -w '\nHTTP %{http_code}\n' \
    -H "Authorization: Bearer $(fly secrets show GROQ_API_KEY -a director-cut)" \
    https://api.groq.com/openai/v1/models

---

## STEP 3 — Deploy missing routes and schema fixes

### 3a. Route: GET /api/runs/{run_id}/errors
This route must be declared BEFORE GET /{run_id} in routes/runs.py so FastAPI
doesn't swallow "/errors" as a run_id. Confirm the file looks like:

  @router.get("/{run_id}/errors")
  async def get_run_errors(run_id: str): ...

  @router.get("/{run_id}/outputs")
  async def get_run_outputs(...): ...

  @router.get("/{run_id}", response_model=RunOut)
  async def get_run(run_id: str): ...

### 3b. last_error on RunOut
schemas/run.py RunOut should have:
  last_error: Optional[str] = None

And get_run() should query the errors table and populate it:
  err_row = await pool.fetchrow(
      "SELECT message FROM errors WHERE run_id=$1 ORDER BY created_at DESC LIMIT 1",
      run_id
  )
  last_error = str(err_row["message"]) if err_row else None

This means a single GET /api/runs/{id} call always shows the failure reason
without needing a second /errors call.

---

## STEP 4 — Verify the pipeline stages actually work

Once a run reaches planning and beyond, it needs:
  - GROQ_API_KEY for LLM calls (intake → planning → script → storyboard → QA)
  - FAL_KEY for image/video generation (assets → render)

Test each dependency independently:

### LLM (Groq)
  curl -sS -w '\nHTTP %{http_code}\n' \
    -H "Authorization: Bearer $GROQ_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{"model":"llama3-8b-8192","messages":[{"role":"user","content":"say hello"}],"max_tokens":10}' \
    https://api.groq.com/openai/v1/chat/completions

Expected: HTTP 200 + JSON with "choices".

### Image generation (Fal)
  curl -sS -w '\nHTTP %{http_code}\n' \
    -H "Authorization: Key $FAL_KEY" \
    https://fal.run/fal-ai/fast-sdxl

Expected: HTTP 200 or method-not-allowed (405) — NOT 401.

If either of these fails → fix the key in Fly:
  fly secrets set GROQ_API_KEY="..." -a director-cut
  fly secrets set FAL_KEY="..." -a director-cut

---

## STEP 5 — End-to-end smoke test (run one after fixing)

After deploying all fixes, create a minimal test run directly against the API:

TOKEN=$(your-fresh-supabase-access-token)
BASE=https://director-cut.fly.dev

# 1. Create a project
PROJECT=$(curl -sS --http1.1 -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"smoke-test","description":"e2e test"}' \
  "$BASE/api/projects/")
PROJECT_ID=$(echo $PROJECT | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "Project: $PROJECT_ID"

# 2. Create a run
RUN=$(curl -sS --http1.1 -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"project_id\":\"$PROJECT_ID\",\"prompt\":\"A single red circle on white background, still image\",\"settings\":{\"target_output\":\"image\",\"scene_count\":1}}" \
  "$BASE/api/runs/")
RUN_ID=$(echo $RUN | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "Run: $RUN_ID"

# 3. Poll for 2 minutes
for i in $(seq 1 24); do
  sleep 5
  STATUS=$(curl -sS --http1.1 -H "Authorization: Bearer $TOKEN" "$BASE/api/runs/$RUN_ID")
  S=$(echo $STATUS | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['status'], d['current_stage'], d.get('last_error',''))")
  echo "[$i] $S"
  echo $STATUS | python3 -c "import sys,json; s=json.load(sys.stdin)['status']; sys.exit(0 if s in ('completed','failed') else 1)" && break
done

# 4. On failure: check errors table
curl -sS --http1.1 -H "Authorization: Bearer $TOKEN" "$BASE/api/runs/$RUN_ID/errors"

# 5. On success: check outputs
curl -sS --http1.1 -H "Authorization: Bearer $TOKEN" "$BASE/api/runs/$RUN_ID/outputs"

---

## STEP 6 — Deploy

fly deploy -a director-cut

Then re-run STEP 5 to confirm end-to-end. A successful run should:
- Pass through intake → planning → script → render → export
- Return status="completed" on GET /api/runs/{id}
- Return at least one image_url or video_url on GET /api/runs/{id}/outputs

---

## Deliverables

1. Fix in routes/runs.py: route order, last_error on RunOut, get_run() query
2. Fix in routes/runs.py: startup failure in create_run properly marks run failed
3. Confirmed GROQ_API_KEY and FAL_KEY valid and set in Fly
4. Confirmed DATABASE_URL connects and all tables exist in Supabase
5. One completed run (status=completed) from the STEP 5 smoke test
6. README note: "To debug failures: GET /api/runs/{id} includes last_error field"
```
