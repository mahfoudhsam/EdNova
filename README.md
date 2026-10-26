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
| 200 + quota headers | Records the headers | Quota shown on the Metrics page |
| Team quota exhausted | Waits the delay the service states (`Retry-After` or message), then retries | Banner with a countdown; the group can keep chatting |
| Mid-size saturated (503) | Falls back to compact for that step; degraded answers are not cached | "Lighter mode" banner and badge |
| Compact saturated (503) | Waits `Retry-After` and retries (twice) | "Retrying in N s" status |
| Request beyond a ceiling (400) | Halves the output budget, trims context, resends once | Nothing, or a clean error message |
| Network error | Retries once | Clean error message, never a frozen screen |
| Waiting on any model | Concurrency cap + per-room queue | Staged progress text with a timer |

The **degraded-mode switch** (Metrics page, `POST /api/admin/chaos`) simulates
a mid-size 503 or a quota wait inside the gateway, so you can test and demo the
fallback on the real platform. Set `ADMIN_TOKEN` before any public demo.

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
  tests/             gateway + pipeline tests against the mock
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
