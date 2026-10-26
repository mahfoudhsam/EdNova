"""Mock OpenAI-compatible server that follows the challenge's error contract.

Use it to develop and test before you have the real base URL / key, and to
rehearse failures you can't trigger on demand on the real platform.

    python tools/mock_llm.py            # serves http://localhost:9000/v1

Models:  mock-compact-1.5b, mock-mid-14b, mock-embed
Chaos (POST http://localhost:9000/__chaos with JSON):
    {"midsize_503": true}               -> mid-size returns 503 + Retry-After
    {"quota_exhausted_s": 5}            -> next requests get 429 "Team quota exhausted" for 5 s
    {"latency_compact": 0.5, "latency_midsize": 4}
    {"reset": true}
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

COMPACT, MIDSIZE, EMBED = "mock-compact-1.5b", "mock-mid-14b", "mock-embed"
MAX_TOKENS_CEILING = 1024
DIM = 64

app = FastAPI(title="EdNova mock LLM")

DEFAULT_CHAOS = {"midsize_503": False, "quota_until": 0.0, "latency_compact": 0.3, "latency_midsize": 1.5}
chaos = dict(DEFAULT_CHAOS)
bucket = {"tokens": 60.0, "updated": time.time()}
RATE_PER_S, CEILING = 1.0, 60.0


def _refill() -> float:
    t = time.time()
    bucket["tokens"] = min(CEILING, bucket["tokens"] + (t - bucket["updated"]) * RATE_PER_S)
    bucket["updated"] = t
    return bucket["tokens"]


def _quota_headers() -> dict:
    return {"x-ratelimit-remaining-requests": str(int(_refill())), "x-ratelimit-limit-requests": str(int(CEILING))}


def _error(status: int, message: str, etype: str, headers: dict | None = None) -> JSONResponse:
    return JSONResponse({"error": {"message": message, "type": etype}}, status_code=status, headers=headers or {})


@app.post("/__chaos")
async def set_chaos(req: Request):
    body = await req.json()
    if body.get("reset"):
        chaos.clear(); chaos.update(DEFAULT_CHAOS)
    if "midsize_503" in body:
        chaos["midsize_503"] = bool(body["midsize_503"])
    if "quota_exhausted_s" in body:
        chaos["quota_until"] = time.time() + float(body["quota_exhausted_s"])
    for k in ("latency_compact", "latency_midsize"):
        if k in body:
            chaos[k] = float(body[k])
    return chaos


@app.get("/v1/models")
async def models():
    return {"object": "list", "data": [{"id": m, "object": "model"} for m in (COMPACT, MIDSIZE, EMBED)]}


def _gate() -> JSONResponse | None:
    remaining = chaos["quota_until"] - time.time()
    if remaining > 0:
        delay = max(1, math.ceil(remaining))
        return _error(429, f"Team quota exhausted. Retry after {delay} seconds.", "quota_exhausted",
                      {"retry-after": str(delay)})
    if _refill() < 1:
        return _error(429, "Team quota exhausted. Retry after 2 seconds.", "quota_exhausted", {"retry-after": "2"})
    bucket["tokens"] -= 1
    return None


@app.post("/v1/chat/completions")
async def chat(req: Request):
    body = await req.json()
    model = body.get("model")
    if model not in (COMPACT, MIDSIZE):
        return _error(404, f"model {model!r} not found", "invalid_request_error")
    if body.get("stream"):
        return _error(400, "streaming is not supported", "invalid_request_error")
    if int(body.get("max_tokens") or 0) > MAX_TOKENS_CEILING:
        return _error(400, f"max_tokens exceeds the ceiling ({MAX_TOKENS_CEILING})", "ceiling_exceeded")
    if (g := _gate()) is not None:
        return g
    if model == MIDSIZE and chaos["midsize_503"]:
        return _error(503, "Model class saturated, retry later.", "model_saturated", {"retry-after": "3"})

    await asyncio.sleep(chaos["latency_midsize" if model == MIDSIZE else "latency_compact"])
    messages = body.get("messages", [])
    system = next((m["content"] for m in messages if m["role"] == "system"), "")
    user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    text = _fake_reply(model, system, user)
    usage = {"prompt_tokens": sum(len(m["content"]) for m in messages) // 4,
             "completion_tokens": len(text) // 4}
    usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
    return JSONResponse(
        {"id": "mock-" + hashlib.md5(text.encode()).hexdigest()[:8], "object": "chat.completion",
         "created": int(time.time()), "model": model,
         "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
         "usage": usage},
        headers=_quota_headers(),
    )


def _fake_reply(model: str, system: str, user: str) -> str:
    u = user.split(": ", 1)[-1] if user.startswith("Learner ") else user
    low = u.lower()
    if "Return ONLY one JSON object" in system:          # triage
        intent = ("explain" if re.search(r"pourquoi|comment|explique|why|how|explain|3lech|kifech|علاش|كيفاش", low)
                  else "greeting" if re.search(r"^(salut|hello|hi|merci)\b", low)
                  else "check" if re.search(r"=|\d", low) else "hint")
        lang = ("darija_arabic" if re.search(r"[؀-ۿ]", u)
                else "darija_latin" if re.search(r"\b(chnowa|3lech|kifech|fhemt|9olli|barcha)\b", low)
                else "en" if re.search(r"\b(the|why|how|what)\b", low) else "fr")
        confused = bool(re.search(r"fhemt|comprends pas|don't get|lost|ما فهمت", low))
        return json.dumps({"intent": intent, "language": lang, "confused": confused,
                           "needs_reasoning": intent == "explain"})
    goal = re.search(r"Current step.*?: (.*)", system) or re.search(r"is on step .*?: (.*)", system)
    goal_txt = goal.group(1).strip() if goal else "cette étape"
    if model == COMPACT and "guide; you do not solve" in system:
        return f"[mock compact hint] Bonne piste ! Pour « {goal_txt} », quelle règle de dérivation s'applique ici ?"
    if model == MIDSIZE or "step-by-step" in system.lower() or "numbered steps" in system:
        return (f"[mock {'mid-size' if model == MIDSIZE else 'compact'} explanation]\n"
                f"1. On cherche : {goal_txt}\n2. On applique la règle du cours, terme par terme.\n"
                f"3. On vérifie le résultat sur un exemple simple.\nÀ toi : quelle est la première règle à utiliser ?")
    return "[mock compact] D'accord ! Revenons à l'exercice : où est-ce que tu bloques ?"


@app.post("/v1/embeddings")
async def embeddings(req: Request):
    body = await req.json()
    inputs = body.get("input")
    inputs = [inputs] if isinstance(inputs, str) else inputs
    data = [{"object": "embedding", "index": i, "embedding": _embed(t)} for i, t in enumerate(inputs)]
    return {"object": "list", "data": data, "model": EMBED,
            "usage": {"prompt_tokens": sum(len(t) // 4 for t in inputs), "total_tokens": sum(len(t) // 4 for t in inputs)}}


def _embed(text: str) -> list[float]:
    """Deterministic bag-of-words hashing vector: similar words -> similar vectors."""
    v = [0.0] * DIM
    for w in re.findall(r"\w{3,}", text.lower()):
        h = int(hashlib.md5(w.encode()).hexdigest(), 16)
        v[h % DIM] += 1.0 if (h >> 8) & 1 else -1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=9000)
