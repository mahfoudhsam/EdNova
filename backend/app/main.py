"""EdNova backend: HTTP API + WebSocket study rooms.

Run (from backend/):  uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import cache, content, db, metrics, rag
from .config import REPO_DIR, settings
from .llm_gateway import GatewayError, get_gateway
from .pipeline import handle_message
from .rooms import Room, registry, now
from .router import router

log = logging.getLogger("ednova")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.conn()
    # Index the exercise bank once (only if empty) so explanations can use RAG.
    if rag.store.count() == 0:
        try:
            n = await rag.index_all(get_gateway())
            log.info("Indexed %d chunks for retrieval", n)
        except Exception as e:  # keyword search keeps working without it
            log.warning("Indexing skipped (%s). Run tools/index_content.py later.", type(e).__name__)
    yield


app = FastAPI(title="EdNova", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------- HTTP API
@app.get("/api/health")
async def health():
    return {"ok": True, "models": settings.models, "base_url_configured": bool(settings.base_url)}


@app.get("/api/exercises")
async def list_exercises():
    return [content.public_exercise(e) for e in content.exercises()]


@app.get("/api/routing")
async def routing_table():
    return {"models": settings.models, "steps": router.table()}


@app.get("/api/metrics")
async def get_metrics(window_s: Optional[float] = None):
    return {"summary": metrics.summary(window_s), "recent": metrics.recent(40)}


@app.get("/api/quota")
async def quota():
    return get_gateway().quota_snapshot()


class ChaosIn(BaseModel):
    midsize_unavailable: Optional[bool] = None
    quota_exhausted_s: Optional[int] = None


def _check_admin(token: Optional[str]) -> None:
    if settings.admin_token and token != settings.admin_token:
        raise HTTPException(status_code=403, detail="admin token required")


@app.post("/api/admin/chaos")
async def set_chaos(body: ChaosIn, x_admin_token: Optional[str] = Header(default=None)):
    """Simulate saturation / quota exhaustion to test and demo degraded mode."""
    _check_admin(x_admin_token)
    gw = get_gateway()
    if body.midsize_unavailable is not None:
        gw.chaos.midsize_unavailable = body.midsize_unavailable
    if body.quota_exhausted_s is not None:
        gw.chaos.quota_exhausted_s = max(0, min(60, body.quota_exhausted_s))
    return gw.chaos.__dict__


@app.post("/api/admin/cache/clear")
async def clear_cache(x_admin_token: Optional[str] = Header(default=None)):
    _check_admin(x_admin_token)
    cache.clear()
    return {"ok": True}


# --------------------------------------------------------------- WebSocket
@app.websocket("/ws/rooms/{room_id}")
async def room_socket(ws: WebSocket, room_id: str):
    room_id = "".join(ch for ch in room_id.upper() if ch.isalnum())[:12] or "SOLO"
    await ws.accept()
    room = registry.get_or_create(room_id)
    if len(room.members) >= 6:
        await ws.send_text(json.dumps({"type": "error", "text": "This room is full (6 learners max)."}))
        await ws.close()
        return
    me = room.add_member(ws)
    await ws.send_text(json.dumps({"type": "welcome", "you": {"id": me.id, "label": me.label},
                                   "state": room.state_public(), "history": list(room.history)},
                                  ensure_ascii=False))
    await room.broadcast({"type": "members", "members": room.members_public()})
    await room.broadcast({"type": "system", "text": f"{me.label} joined", "ts": now()})

    try:
        while True:
            data = json.loads(await ws.receive_text())
            kind = data.get("type")

            if kind == "message":
                text = str(data.get("text", "")).strip()[:2000]
                if not text:
                    continue
                me.messages_sent += 1
                await room.broadcast({"type": "message", "from": me.label, "from_id": me.id,
                                      "text": text, "ts": now()}, record=True)
                await room.broadcast({"type": "members", "members": room.members_public()})
                # In a group, the AI answers only when asked (saves quota, keeps peers talking).
                # Alone in the room, every message goes to the AI.
                if data.get("ask_ai") or len(room.members) == 1:
                    asyncio.create_task(_answer(room, text, me.label))

            elif kind == "set_exercise":
                try:
                    room.set_exercise(str(data.get("exercise_id")))
                except KeyError:
                    continue
                await room.broadcast({"type": "state", "state": room.state_public()})
                await room.broadcast({"type": "system", "text": f"{me.label} opened \"{room.exercise['title']}\"", "ts": now()})

            elif kind == "set_step":
                room.set_step(int(data.get("step_index", 0)))
                await room.broadcast({"type": "state", "state": room.state_public()})

    except WebSocketDisconnect:
        pass
    except Exception as e:  # malformed input etc.
        log.warning("socket error: %s", type(e).__name__)
    finally:
        room.remove_member(me.id)
        if room.members:
            await room.broadcast({"type": "members", "members": room.members_public()})
            await room.broadcast({"type": "system", "text": f"{me.label} left", "ts": now()})
        registry.cleanup(room.id)


async def _answer(room: Room, text: str, asked_by: str) -> None:
    async def emit(event: dict) -> None:
        await room.broadcast({"type": "ai_status", **event})
        # Degraded-mode banners everyone in the room should see.
        if event.get("kind") == "midsize_busy":
            await room.broadcast({"type": "banner", "level": "warn", "text":
                                  "Lighter mode: the large model is busy, so answers are shorter for now."})
        elif event.get("kind") == "quota_wait":
            await room.broadcast({"type": "banner", "level": "info", "seconds": event.get("seconds"),
                                  "text": "Team quota reached. EdNova will answer in a few seconds - keep discussing meanwhile."})

    if room.ai_lock.locked():
        await room.broadcast({"type": "ai_status", "kind": "queued", "label": "Waiting for the previous answer"})
    async with room.ai_lock:          # one AI request per room at a time
        await room.broadcast({"type": "ai_status", "kind": "start", "asked_by": asked_by})
        try:
            reply = await handle_message(get_gateway(), room, text, emit)
            await room.broadcast({"type": "ai_message", "asked_by": asked_by, "ts": now(), **reply}, record=True)
            await room.broadcast({"type": "state", "state": room.state_public()})
        except GatewayError as e:
            await room.broadcast({"type": "ai_error", "text": e.user_message, "ts": now()})
        except Exception:
            log.exception("pipeline failure")
            await room.broadcast({"type": "ai_error", "text": "Something went wrong on our side. Try again.", "ts": now()})
        finally:
            await room.broadcast({"type": "ai_status", "kind": "done"})


# ------------------------------------------------- built frontend (optional)
DIST = REPO_DIR / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    async def spa(path: str):
        f = DIST / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
