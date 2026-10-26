"""Exact-match answer cache.

The challenge says apps "must avoid regenerating an answer already obtained for
an equivalent request", and organisers track repeated identical requests.
Baseline = exact match on a normalised key. A semantic layer (embeddings +
similarity threshold) is planned for v4.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from typing import Optional

from . import db


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower().strip()
    text = re.sub(r"[\s]+", " ", text)
    text = re.sub(r"[\s?!.؟،,;:]+$", "", text)  # trailing punctuation (Latin + Arabic)
    return text


def make_key(*parts: str) -> str:
    raw = "␟".join(normalize(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get(key: str) -> Optional[dict]:
    rows = db.query("SELECT value FROM cache WHERE key = ?", (key,))
    if not rows:
        return None
    db.execute("UPDATE cache SET hits = hits + 1 WHERE key = ?", (key,))
    return json.loads(rows[0]["value"])


def put(key: str, value: dict) -> None:
    db.execute(
        "INSERT OR REPLACE INTO cache (key, value, created, hits) VALUES (?,?,?,0)",
        (key, json.dumps(value, ensure_ascii=False), time.time()),
    )


def clear() -> None:
    db.execute("DELETE FROM cache")
