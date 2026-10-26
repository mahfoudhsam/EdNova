"""Retrieval over the exercise bank and glossary.

The platform deploys a vector database with one collection per team. Its exact
client API is communicated with the base URL, so retrieval sits behind the small
`VectorStore` interface below. The baseline ships `SqliteVectorStore`: vectors
come from the platform's embeddings endpoint and are stored locally. When you
get the platform's vector DB details, add a `PlatformVectorStore` with the same
two methods and switch `store` at the bottom of this file.
"""
from __future__ import annotations

import json
import math
import re
from collections import OrderedDict
from typing import Optional, Protocol

from . import content, db
from .llm_gateway import GatewayError, LLMGateway


class VectorStore(Protocol):
    def add(self, rows: list[dict]) -> None: ...
    def search(self, vector: list[float], k: int, exercise_id: Optional[str]) -> list[dict]: ...
    def count(self) -> int: ...


class SqliteVectorStore:
    def add(self, rows: list[dict]) -> None:
        db.executemany(
            "INSERT OR REPLACE INTO chunks (id, exercise_id, kind, text, embedding) VALUES (?,?,?,?,?)",
            [(r["id"], r.get("exercise_id"), r["kind"], r["text"], json.dumps(r["embedding"])) for r in rows],
        )

    def search(self, vector: list[float], k: int, exercise_id: Optional[str]) -> list[dict]:
        if exercise_id:
            rows = db.query("SELECT * FROM chunks WHERE exercise_id = ? OR exercise_id IS NULL", (exercise_id,))
        else:
            rows = db.query("SELECT * FROM chunks")
        scored = []
        for r in rows:
            emb = json.loads(r["embedding"])
            scored.append((_cosine(vector, emb), {"id": r["id"], "kind": r["kind"], "text": r["text"]}))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [dict(item, score=round(s, 3)) for s, item in scored[:k]]

    def count(self) -> int:
        return db.query("SELECT COUNT(*) AS n FROM chunks")[0]["n"]


store: VectorStore = SqliteVectorStore()

# Small in-memory LRU for query embeddings: identical questions cost no embedding call.
_query_cache: "OrderedDict[str, list[float]]" = OrderedDict()
_QUERY_CACHE_MAX = 512


def build_chunks() -> list[dict]:
    chunks = []
    for ex in content.exercises():
        chunks.append({"id": f"{ex['id']}:statement", "exercise_id": ex["id"], "kind": "statement",
                       "text": f"{ex['title']}. {ex['statement']}"})
        for i, s in enumerate(ex["steps"], start=1):
            chunks.append({"id": f"{ex['id']}:step{i}", "exercise_id": ex["id"], "kind": "step",
                           "text": f"{ex['title']} - étape {i}: {s['goal']} {s['work']} Erreur fréquente: {s.get('misconception', '')}"})
    for j, g in enumerate(content.glossary()):
        chunks.append({"id": f"glossary:{j}", "exercise_id": None, "kind": "glossary",
                       "text": " | ".join(f"{k}: {v}" for k, v in g.items())})
    return chunks


async def index_all(gateway: LLMGateway, batch_size: int = 16) -> int:
    """Embed every chunk in a few batched calls (uses the burst reserve once)."""
    chunks = build_chunks()
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        vectors = await gateway.embed([c["text"] for c in batch])
        for c, v in zip(batch, vectors):
            c["embedding"] = v
        store.add(batch)
    return len(chunks)


async def search(gateway: LLMGateway, query: str, exercise_id: Optional[str] = None, k: int = 3) -> list[dict]:
    if store.count() == 0:
        return keyword_search(query, exercise_id, k)
    key = query.strip().lower()
    vector = _query_cache.get(key)
    if vector is None:
        try:
            vector = (await gateway.embed([query]))[0]
        except GatewayError:
            return keyword_search(query, exercise_id, k)   # degrade, don't fail
        _query_cache[key] = vector
        if len(_query_cache) > _QUERY_CACHE_MAX:
            _query_cache.popitem(last=False)
    else:
        _query_cache.move_to_end(key)
    return store.search(vector, k, exercise_id)


def keyword_search(query: str, exercise_id: Optional[str], k: int) -> list[dict]:
    """Zero-cost fallback when embeddings are unavailable."""
    words = set(re.findall(r"\w{3,}", query.lower()))
    scored = []
    for c in build_chunks():
        if exercise_id and c["exercise_id"] not in (exercise_id, None):
            continue
        overlap = len(words & set(re.findall(r"\w{3,}", c["text"].lower())))
        scored.append((overlap, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{"id": c["id"], "kind": c["kind"], "text": c["text"], "score": s} for s, c in scored[:k]]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)
