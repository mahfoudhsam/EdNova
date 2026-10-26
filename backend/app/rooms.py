"""In-memory study rooms (one room = one group session, or a solo session).

Privacy by design: learners get pseudonyms ("Learner A"); no names, photos or
voices are collected. Room state lives in memory and disappears on restart.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

from . import content

LABELS = [f"Learner {c}" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]
MAX_MEMBERS = 6


@dataclass
class Member:
    id: str
    label: str
    ws: WebSocket
    messages_sent: int = 0          # talk share, used by the facilitator in v2


@dataclass
class Room:
    id: str
    exercise_id: str
    step_index: int = 0
    hint_level: int = 0             # grows each time the room asks for a hint on this step
    confused_streak: int = 0
    members: dict[str, Member] = field(default_factory=dict)
    history: deque = field(default_factory=lambda: deque(maxlen=40))
    ai_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # ---------------------------------------------------------------- members
    def add_member(self, ws: WebSocket) -> Member:
        used = {m.label for m in self.members.values()}
        label = next(l for l in LABELS if l not in used)
        m = Member(id=uuid.uuid4().hex[:8], label=label, ws=ws)
        self.members[m.id] = m
        return m

    def remove_member(self, member_id: str) -> None:
        self.members.pop(member_id, None)

    def members_public(self) -> list[dict]:
        return [{"id": m.id, "label": m.label, "messages": m.messages_sent} for m in self.members.values()]

    # --------------------------------------------------------------- exercise
    @property
    def exercise(self) -> dict:
        return content.exercise(self.exercise_id)

    @property
    def step(self) -> dict:
        return self.exercise["steps"][self.step_index]

    def set_exercise(self, exercise_id: str) -> None:
        content.exercise(exercise_id)  # validates
        self.exercise_id = exercise_id
        self.step_index = 0
        self._reset_step_state()

    def set_step(self, index: int) -> None:
        n = len(self.exercise["steps"])
        self.step_index = max(0, min(n - 1, index))
        self._reset_step_state()

    def _reset_step_state(self) -> None:
        self.hint_level = 0
        self.confused_streak = 0

    def state_public(self) -> dict:
        return {
            "room_id": self.id,
            "exercise": content.public_exercise(self.exercise),
            "step_index": self.step_index,
            "hint_level": self.hint_level,
            "members": self.members_public(),
        }

    # -------------------------------------------------------------- messaging
    async def broadcast(self, event: dict[str, Any], record: bool = False) -> None:
        if record:
            self.history.append(event)
        data = json.dumps(event, ensure_ascii=False)
        dead = []
        for m in list(self.members.values()):
            try:
                await m.ws.send_text(data)
            except Exception:
                dead.append(m.id)
        for mid in dead:
            self.remove_member(mid)


class RoomRegistry:
    def __init__(self) -> None:
        self.rooms: dict[str, Room] = {}

    def get_or_create(self, room_id: str) -> Room:
        room = self.rooms.get(room_id)
        if room is None:
            room = Room(id=room_id, exercise_id=content.exercises()[0]["id"])
            self.rooms[room_id] = room
        return room

    def cleanup(self, room_id: str) -> None:
        room = self.rooms.get(room_id)
        if room and not room.members:
            self.rooms.pop(room_id, None)


registry = RoomRegistry()


def now() -> float:
    return round(time.time(), 3)
