# Progress log

Running record of what's been done on top of the EdNova baseline, kept
separate from `README.md` (which documents the app as it stands) so the
history of *why* things changed survives even as the README gets rewritten.
Newest entry on top. Each entry maps to one or more git commits.

---

## 2026-10-27 — Foundations + three correctness/resilience fixes

Starting point: a working baseline (v0) with no git history, a broken Windows
venv, and a few gaps found by reading the gateway/pipeline/RAG code against
the challenge's spec book and API guide.

### Foundations
- Fixed the Windows venv instructions in the README: the old quick-start line
  (`python -m venv .venv && source .venv/bin/activate # Windows: ...`) led
  people to pass `.venv\Scripts\activate` as the venv's *target path*, which
  creates a broken nested venv (`backend\.venv\Scripts\activate\Scripts\activate`)
  instead of a working one at `backend\.venv`. Replaced it with separate,
  correct macOS/Linux and Windows PowerShell blocks, plus a note on how to
  spot and fix an already-broken venv.
- `git init`, confirmed `.gitignore` already excludes `.env`, `.venv/`,
  `node_modules/`, `*.sqlite3`; initial commit of the baseline as-is.
- Rebuilt the backend venv, installed `requirements.txt`, confirmed `pytest`
  was green before changing anything (13 tests passing at that point).

### Fix 1 — hint ladder was unbounded, which silently killed its own cache
`backend/app/pipeline.py`: `room.hint_level` fed the exact-match cache key
(`cache.make_key(text, exercise_id, step_index, hint_level)`) but grew by one
on every hint request forever. The hint prompt only defines three rungs
(0 = gentle nudge, 1 = guiding question, 2 = show the first move), so any
request past rung 2 minted a cache key that could never be reused — the
per-step cache was dead weight for any learner who kept asking past the third
hint. *(Note: an earlier description of this as "a learner gets stuck on the
same hint forever" was wrong on re-tracing — the real, verified bug is the
unbounded growth defeating the cache, not a stuck ladder.)*

**Fix:** capped `room.hint_level` at `MAX_HINT_LEVEL = 2` when incrementing.
Added `test_hint_level_caps_at_top_rung_and_cache_is_reused`.

### Fix 2 — quota was only ever handled reactively
The API guide (section 5) asks apps to "read the remaining quota and pace
requests accordingly." The gateway previously only reacted *after* a
429/503. Added a proactive path:
- `QuotaState` now parses `remaining`/`limit` out of the response headers it
  already recorded.
- `LLMGateway._should_pace_down()`: true when `remaining/limit` falls below
  `QUOTA_PACING_THRESHOLD` (new setting, default 0.2 / 20%).
- `chat()` checks this once per call: a mid-size step with a configured
  fallback proactively uses the fallback class instead of spending a scarce
  mid-size slot on a call likely to fail.
- `LLMResult.fallback_reason` (`"pacing"` vs `"saturated"`) keeps this
  distinguishable from a reactive 503 fallback everywhere it surfaces: the
  cached `route_reason` text, the `"pacing"` status event, and the room
  banner ("Conserving the team's shared quota...").
- `quota_snapshot()` now also exposes `remaining`/`limit`/`pacing_threshold`.

Tests: low quota paces down with no error involved; healthy quota doesn't;
headers actually populate `remaining`/`limit`.

### Fix 3 — embeddings path wasn't resilient at all
`LLMGateway.embed()` raised on the very first error, with no retry, and never
caught `APITimeoutError`/`APIConnectionError` — only `APIStatusError`. Since
`rag.search()`'s fallback (`except GatewayError: return keyword_search(...)`)
only catches `GatewayError`, a plain network blip on the embeddings endpoint
bypassed that intended "degrade, don't fail" path entirely and surfaced as a
generic pipeline failure instead of a quiet fallback to keyword search.

**Fix:** `embed()` now retries once on a transient quota/saturation signal or
a network error, then raises `GatewayError` either way, so every failure path
is catchable by `rag.search()`.

Also discovered the mock server's `/v1/embeddings` endpoint didn't simulate
*any* failures, so this path was untestable. Added two chaos controls to
`tools/mock_llm.py`:
- `embed_fail_once` — one transient blip, recovers on the retry.
- `embed_down` — sustained outage, exercises the full give-up-and-degrade
  path.

New `backend/tests/test_rag.py` covers the degrade-to-keyword-search path
end to end; `test_gateway.py` covers `embed()`'s retry/give-up logic and the
network-error-to-`GatewayError` conversion directly (using a monkeypatched
`APIConnectionError`).

### Docs
Added a "Simulating failures" section to the README with the exact
curl/PowerShell commands for every chaos control (mock-server chaos, backend
admin chaos, and how to trigger/observe quota pacing without any chaos at
all) — meant to double as the demo-video script.

**Test count: 13 → 22, all passing.**
**Commits:** `60255b8` (initial), `f6be3f0` (hint cap), `2d3f430` (quota
pacing), `36f4c66` (embeddings resilience + docs).

### Deliberately not done yet
These were flagged as real gaps against the spec book but are feature work,
not foundation work, so they're left for the next phase once the target
feature set is settled:
- No diagnostic step to find a learner's preferred learning style (spec
  Goal 2).
- No "suggest the next learning step" (spec Goal 1).
- Content is 5 derivative exercises only.
- Compact-class pacing / request spacing (only mid-size→compact pacing is
  implemented so far).
