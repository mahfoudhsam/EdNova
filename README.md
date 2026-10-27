# EdNova — GenAI Peer Learning Companion (baseline)

A group study room where learners work through an exercise together and an AI
companion gives **hints before answers**, in Tunisian Darija, French, Arabic or
English. Built for the IEEE WIE ACT 5.0 EdNova technical challenge.

This is the **baseline (v0)**: the full request path works end to end, with no
advanced features yet. Every later feature plugs into it.

```
learner message ─▶ rule shortcut ─▶ exact cache ─▶ compact triage (1 JSON call)
                                         │ hit             │
                                         ▼                 ├─ greeting / off-topic ─▶ compact short reply
                                    instant reply          ├─ stuck / check answer  ─▶ compact hint (grounded in the step)
                                                           └─ why / how / confused×2 ─▶ RAG ─▶ mid-size explanation
                                                                                             └─ 503 ─▶ compact fallback ("lighter mode")
reply + model badge + reason ─▶ cache ─▶ metrics row
```

## Quick start (mock models, no key needed)

Requirements: Python 3.10+, Node 18+. All commands start from the repo root.

**macOS / Linux (bash, zsh)**

```bash
# 1. config
cp .env.example .env

# 2. backend deps (one-time)
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. terminal A: mock OpenAI-compatible server (follows the challenge's error contract)
cd backend && source .venv/bin/activate
python ../tools/mock_llm.py                              # http://localhost:9000/v1

# 4. terminal B: backend
cd backend && source .venv/bin/activate
uvicorn app.main:app --reload --port 8000                # http://localhost:8000

# 5. terminal C: frontend
cd frontend
npm install
npm run dev                                              # http://localhost:5173
```

**Windows (PowerShell)**

```powershell
# 1. config
Copy-Item .env.example .env

# 2. backend deps (one-time)
cd backend
python -m venv .venv                 # the folder is just ".venv", nothing more
.venv\Scripts\Activate.ps1           # the activation script, not part of the venv path
pip install -r requirements.txt

# 3. terminal A: mock server
cd backend; .venv\Scripts\Activate.ps1
python ..\tools\mock_llm.py

# 4. terminal B: backend
cd backend; .venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8000

# 5. terminal C: frontend
cd frontend
npm install
npm run dev
```

If PowerShell refuses to run `Activate.ps1`, allow local scripts once with
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. In `cmd.exe`, use
`.venv\Scripts\activate.bat` instead. Windows PowerShell 5.1 has no `&&`, so
run the commands one per line (or chain them with `;`).

You should see `(.venv)` at the start of your prompt after activating. If
`backend\.venv` contains a nested `Scripts\activate\` folder, the venv was
created at the wrong path: delete `backend\.venv` and repeat step 2.

Open http://localhost:5173, start a room, and open the same room link in a
second browser window to act as a second learner. The **Metrics** page shows
the compact / mid-size split, cache hits, latency and the degraded-mode switch.

Single-port mode: run `npm run build` in `frontend/`, then the backend serves
the built UI at http://localhost:8000.

Tests (gateway error contract + pipeline, run against the mock in-process),
from `backend/` with the venv active:

```bash
pytest -q
```

## Switching to the real platform

1. Put the organisers' base URL and your team key in `.env` (never in code).
2. List the models: `curl -H "Authorization: Bearer $EDNOVA_API_KEY" $EDNOVA_BASE_URL/models`
   and set `COMPACT_MODEL`, `MIDSIZE_MODEL`, `EMBEDDING_MODEL`.
3. Run the benchmark (scores both classes on 22 tutoring and Darija prompts):
   `cd backend && python ../tools/benchmark.py` → fill the score columns in
   `benchmark_results.csv`. Use the results to tune `routing.yaml` and the
   language policy, and cite them in the technical report.
4. Re-index the content into the vector store: `python ../tools/index_content.py --reset`.
5. When you receive the platform vector DB details, add a `PlatformVectorStore`
   in `backend/app/rag.py` (same `add` / `search` / `count` interface).

Local models instead of the mock: run Ollama (`ollama pull qwen2.5:1.5b`,
`qwen2.5:14b`, `nomic-embed-text`) and use the commented block in
`.env.example`. To rehearse failures with real models, put
`tools/fault_proxy.py` in front of Ollama.

## Model routing table

Defined in `backend/routing.yaml` and shown live on the Metrics page.

| Step | Model class | Max output | Fallback | Why |
| --- | --- | --- | --- | --- |
| triage | compact | 120 | – | Classification (intent, language, confusion), short JSON |
| chat | compact | 120 | – | Greetings and off-topic redirects |
| hint | compact | 160 | – | One guiding question grounded in the current solution step |
| explain | mid-size | 450 | compact | Step-by-step reasoning and learner-facing writing |

Zero-call paths: greetings are handled by a rule; repeated questions are served
from the cache; a group message only reaches the AI when a learner presses
**Ask EdNova** (alone in a room, every message does).

## Degraded-mode behaviour (the API guide's error contract)

All handled in `backend/app/llm_gateway.py`, the only module that calls the API.

| Situation | What the app does | What the learner sees |
| --- | --- | --- |
| 200 + quota headers | Records the headers (remaining / limit) | Quota shown on the Metrics page |
| Remaining quota below `QUOTA_PACING_THRESHOLD` (20% by default) | Proactively uses the fallback class for mid-size steps, *before* spending a call that would likely fail | "Conserving quota" banner and badge — this is a deliberate pace-down, not an error |
| Team quota exhausted | Waits the delay the service states (`Retry-After` or message), then retries | Banner with a countdown; the group can keep chatting |
| Mid-size saturated (503) | Falls back to compact for that step; degraded answers are not cached | "Lighter mode" banner and badge |
| Compact saturated (503) | Waits `Retry-After` and retries (twice) | "Retrying in N s" status |
| Request beyond a ceiling (400) | Halves the output budget, trims context, resends once | Nothing, or a clean error message |
| Network error (chat) | Retries once | Clean error message, never a frozen screen |
| Embeddings saturated (503) / quota (429) / network error | Retries once, then raises a clean error | `rag.search()` catches it and degrades to keyword search — the explain step still answers, just without vector ranking |
| Waiting on any model | Concurrency cap + per-room queue | Staged progress text with a timer |

Pacing (`LLMGateway._should_pace_down`) and reactive fallback (after an actual
503) share the same compact-class path, but are logged and surfaced
separately (`fallback_reason`: `"pacing"` vs `"saturated"`) so the Metrics
page and the technical report can show how often each one fired.

The **degraded-mode switch** (Metrics page, `POST /api/admin/chaos`) simulates
a mid-size 503 or a quota wait inside the gateway, so you can test and demo the
fallback on the real platform. Set `ADMIN_TOKEN` before any public demo.

## Simulating failures (exact commands)

Two independent places can inject failures, for two different purposes:

- **`tools/mock_llm.py`'s `/__chaos` endpoint** — the server lies about what
  happened (returns real 503/429 HTTP responses). Use this to prove the
  gateway's retry/fallback/degrade logic against realistic server behaviour,
  including in the automated tests.
- **The backend's `/api/admin/chaos` endpoint** (`main.py`) — the gateway
  pretends a call failed without actually calling the server. Use this for a
  live demo in front of the jury: toggle it while a room is open and watch the
  banners change in real time.

Run these with terminal A (mock server) and terminal B (backend) from the
[Quick start](#quick-start-mock-models-no-key-needed) already up.

**1. Mock server chaos — `http://localhost:9000/__chaos`**

| Scenario | macOS/Linux (curl) | Windows (PowerShell) |
| --- | --- | --- |
| Mid-size returns 503 | `curl -X POST localhost:9000/__chaos -d '{"midsize_503": true}'` | `irm localhost:9000/__chaos -Method Post -Body '{"midsize_503": true}'` |
| Team quota exhausted for 5s | `curl -X POST localhost:9000/__chaos -d '{"quota_exhausted_s": 5}'` | `irm localhost:9000/__chaos -Method Post -Body '{"quota_exhausted_s": 5}'` |
| Embeddings: one transient blip (recovers on retry) | `curl -X POST localhost:9000/__chaos -d '{"embed_fail_once": true}'` | `irm localhost:9000/__chaos -Method Post -Body '{"embed_fail_once": true}'` |
| Embeddings: sustained outage (explain falls back to keyword search) | `curl -X POST localhost:9000/__chaos -d '{"embed_down": true}'` | `irm localhost:9000/__chaos -Method Post -Body '{"embed_down": true}'` |
| Slow down responses (test staged progress UI) | `curl -X POST localhost:9000/__chaos -d '{"latency_midsize": 6}'` | `irm localhost:9000/__chaos -Method Post -Body '{"latency_midsize": 6}'` |
| Reset everything to defaults | `curl -X POST localhost:9000/__chaos -d '{"reset": true}'` | `irm localhost:9000/__chaos -Method Post -Body '{"reset": true}'` |

After each one, ask EdNova something in the open room and watch the badge /
banner; `embed_down` only shows up on an "explain"-routed question (ask "why"
or "how"), since that's the only step that calls RAG.

**2. Backend admin chaos — `http://localhost:8000/api/admin/chaos`**

Set `ADMIN_TOKEN` in `.env` first if you want this protected (leave it blank
for local dev). Add `-H "X-Admin-Token: <token>"` / `-Headers @{ "X-Admin-Token" = "<token>" }` if you did.

| Scenario | macOS/Linux (curl) | Windows (PowerShell) |
| --- | --- | --- |
| Force mid-size unavailable | `curl -X POST localhost:8000/api/admin/chaos -d '{"midsize_unavailable": true}'` | `irm localhost:8000/api/admin/chaos -Method Post -Body '{"midsize_unavailable": true}'` |
| Force a quota wait (seconds) | `curl -X POST localhost:8000/api/admin/chaos -d '{"quota_exhausted_s": 8}'` | `irm localhost:8000/api/admin/chaos -Method Post -Body '{"quota_exhausted_s": 8}'` |
| Turn mid-size back on | `curl -X POST localhost:8000/api/admin/chaos -d '{"midsize_unavailable": false}'` | `irm localhost:8000/api/admin/chaos -Method Post -Body '{"midsize_unavailable": false}'` |

**3. Quota pacing (no chaos needed)** — ask several "why"/"how" questions in a
row; once `gateway.quota.remaining / limit` drops under `QUOTA_PACING_THRESHOLD`
(20% by default — the mock's bucket holds 60 tokens, so roughly after the
first dozen calls), the next explain request proactively answers with compact
and shows the "Conserving quota" banner, with no error involved. Watch it
directly: `curl localhost:8000/api/quota` / `irm localhost:8000/api/quota`.

**4. Automated regression coverage of all of the above**, from `backend/`
with the venv active:

```bash
pytest -q
```

Relevant files: `tests/test_gateway.py` (error contract, pacing, embeddings
retry/give-up), `tests/test_rag.py` (embeddings outage → keyword-search
degrade), `tests/test_pipeline.py` (end-to-end routing and caching).

## Repository layout

```
backend/
  app/
    main.py          FastAPI app: HTTP API + WebSocket study rooms
    llm_gateway.py   the only API caller: routing, retries, fallback, quota, metrics
    router.py        loads routing.yaml
    pipeline.py      rule -> cache -> triage -> route -> RAG -> generate
    rooms.py         in-memory rooms, pseudonymous learners, talk share
    rag.py           retrieval (VectorStore interface + SQLite stand-in)
    cache.py         exact-match answer cache
    metrics.py       per-call log + summary (metadata only)
    content.py       exercise bank + prompt templates
    prompts/         triage.txt, hint.txt, explain.txt, chat.txt
  routing.yaml       which model class handles which step
  tests/             gateway + pipeline + RAG tests against the mock
frontend/            Vite + React: join page, study room, metrics page
content/
  exercises.json     5 Bac exercises (derivatives) with worked steps, hints, misconceptions + glossary
tools/
  mock_llm.py        mock OpenAI-compatible server with chaos controls
  fault_proxy.py     inject 503 / quota errors in front of any server (e.g. Ollama)
  benchmark.py       compare both classes on benchmark_prompts.jsonl
  index_content.py   batch-index the content for retrieval
```

## Privacy and platform rules

- Learners are pseudonymous ("Learner A"); no names, photos or voices are collected.
- Room state lives in memory; the SQLite log stores call metadata only (no message text, no key).
- The browser never receives worked solutions, only exercise statements and step goals.
- Only public, fictional, synthetic or anonymised data should be sent to the service.
- The key lives in `.env`, which is git-ignored. Check screenshots and videos before sharing.

## Roadmap (each version stays submittable)

| Version | Adds | Where |
| --- | --- | --- |
| v1 | Full hint ladder (4 levels, answer unlock rules), answer-leak guard, quiz check step | `pipeline.py`, `prompts/`, `routing.yaml` |
| v2 | Group mechanics: facilitator nudges from talk share, blind answers, "I'm lost" button | `rooms.py`, `main.py`, frontend |
| v3 | Diagnostic onboarding, mastery per skill (pyBKT), format switching | new `learner_model.py` |
| v4 | Hint Coins, Ghost Classmate, Night Shift pre-generation, semantic cache | `cache.py`, `tools/` |
| v5 | Teacher dashboard, session wrap-up notes (mid-size, once), Darija few-shots | frontend, `prompts/` |
