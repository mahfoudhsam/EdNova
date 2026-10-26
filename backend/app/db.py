"""Tiny SQLite layer shared by metrics, cache and the RAG stand-in.

SQLite keeps setup to zero. Swap for Postgres/Redis later if you need to scale.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from .config import settings

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    step TEXT NOT NULL,
    model_class TEXT NOT NULL,      -- compact | midsize | cache | none
    model TEXT,
    status INTEGER,                 -- HTTP status, 0 = network error, -1 = simulated
    latency_ms INTEGER,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    cache_hit INTEGER DEFAULT 0,
    fell_back INTEGER DEFAULT 0,
    route_reason TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_calls_ts ON calls(ts);

CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,            -- JSON payload of the reply
    created REAL NOT NULL,
    hits INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    exercise_id TEXT,
    kind TEXT,                      -- statement | step | glossary
    text TEXT NOT NULL,
    embedding TEXT NOT NULL         -- JSON list of floats
);
"""


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(settings.db_path, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(SCHEMA)
        _conn.commit()
    return _conn


def execute(sql: str, params: tuple = ()) -> None:
    with _lock:
        c = conn()
        c.execute(sql, params)
        c.commit()


def executemany(sql: str, rows: list[tuple]) -> None:
    with _lock:
        c = conn()
        c.executemany(sql, rows)
        c.commit()


def query(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    with _lock:
        return conn().execute(sql, params).fetchall()


def reset_for_tests(path: str) -> None:
    """Point the DB at a fresh file (used by tests)."""
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn = None
        settings.db_path = path
