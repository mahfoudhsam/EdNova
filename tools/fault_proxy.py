"""Fault-injection proxy in front of ANY OpenAI-compatible server (e.g. Ollama).

Lets you rehearse 503s and quota errors with real local models.

    # Ollama exposes http://localhost:11434/v1
    UPSTREAM=http://localhost:11434 MIDSIZE_MODEL=qwen2.5:14b python tools/fault_proxy.py
    # then set EDNOVA_BASE_URL=http://localhost:9100/v1

Chaos: POST http://localhost:9100/__chaos  {"midsize_503": true} | {"quota_exhausted_s": 5} | {"reset": true}
"""
from __future__ import annotations

import json
import math
import os
import time

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

UPSTREAM = os.getenv("UPSTREAM", "http://localhost:11434").rstrip("/")
MIDSIZE_MODEL = os.getenv("MIDSIZE_MODEL", "")
PORT = int(os.getenv("PROXY_PORT", "9100"))

app = FastAPI(title="EdNova fault proxy")
chaos = {"midsize_503": False, "quota_until": 0.0}
client = httpx.AsyncClient(timeout=600)


@app.post("/__chaos")
async def set_chaos(req: Request):
    body = await req.json()
    if body.get("reset"):
        chaos.update(midsize_503=False, quota_until=0.0)
    if "midsize_503" in body:
        chaos["midsize_503"] = bool(body["midsize_503"])
    if "quota_exhausted_s" in body:
        chaos["quota_until"] = time.time() + float(body["quota_exhausted_s"])
    return chaos


@app.api_route("/{path:path}", methods=["GET", "POST"])
async def forward(path: str, req: Request):
    raw = await req.body()
    remaining = chaos["quota_until"] - time.time()
    if remaining > 0 and req.method == "POST":
        d = max(1, math.ceil(remaining))
        return JSONResponse({"error": {"message": f"Team quota exhausted. Retry after {d} seconds.", "type": "quota_exhausted"}},
                            status_code=429, headers={"retry-after": str(d)})
    if chaos["midsize_503"] and raw:
        try:
            if json.loads(raw).get("model") == MIDSIZE_MODEL:
                return JSONResponse({"error": {"message": "Model class saturated", "type": "model_saturated"}},
                                    status_code=503, headers={"retry-after": "3"})
        except ValueError:
            pass
    headers = {k: v for k, v in req.headers.items() if k.lower() not in ("host", "content-length")}
    r = await client.request(req.method, f"{UPSTREAM}/{path}", content=raw, headers=headers, params=req.query_params)
    return Response(r.content, status_code=r.status_code,
                    headers={k: v for k, v in r.headers.items() if k.lower() not in ("content-length", "content-encoding", "transfer-encoding")})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=PORT)
