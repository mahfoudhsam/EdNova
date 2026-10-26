"""All configuration comes from environment variables (.env in dev).

Nothing here is hard-coded: the challenge rules require a configurable base URL
and forbid exposing the team key in code, logs, screenshots or videos.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent

# Load backend/.env first, then repo-root .env (first value wins).
load_dotenv(BACKEND_DIR / ".env")
load_dotenv(REPO_DIR / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


@dataclass
class Settings:
    # --- Platform access -------------------------------------------------
    base_url: str = field(default_factory=lambda: os.getenv("EDNOVA_BASE_URL", "http://localhost:9000/v1"))
    api_key: str = field(default_factory=lambda: os.getenv("EDNOVA_API_KEY", "dev-key"))

    # Model names per class (check GET /v1/models once you have the key)
    compact_model: str = field(default_factory=lambda: os.getenv("COMPACT_MODEL", "mock-compact-1.5b"))
    midsize_model: str = field(default_factory=lambda: os.getenv("MIDSIZE_MODEL", "mock-mid-14b"))
    embedding_model: str = field(default_factory=lambda: os.getenv("EMBEDDING_MODEL", "mock-embed"))

    # --- Client-side limits ---------------------------------------------
    max_concurrency: int = field(default_factory=lambda: _int("MAX_CONCURRENCY", 2))
    request_timeout_s: float = field(default_factory=lambda: _float("REQUEST_TIMEOUT_S", 180))
    max_quota_waits: int = field(default_factory=lambda: _int("MAX_QUOTA_WAITS", 3))
    max_retry_after_s: float = field(default_factory=lambda: _float("MAX_RETRY_AFTER_S", 60))

    # --- Storage ----------------------------------------------------------
    db_path: str = field(default_factory=lambda: os.getenv("DB_PATH", str(BACKEND_DIR / "ednova.sqlite3")))
    content_path: str = field(default_factory=lambda: os.getenv("CONTENT_PATH", str(REPO_DIR / "content" / "exercises.json")))
    routing_path: str = field(default_factory=lambda: os.getenv("ROUTING_PATH", str(BACKEND_DIR / "routing.yaml")))
    prompts_dir: str = field(default_factory=lambda: os.getenv("PROMPTS_DIR", str(BACKEND_DIR / "app" / "prompts")))

    # --- Admin --------------------------------------------------------------
    # Protects /api/admin/* (chaos switch). Empty = no token required (dev only).
    admin_token: str = field(default_factory=lambda: os.getenv("ADMIN_TOKEN", ""))

    @property
    def models(self) -> dict[str, str]:
        return {"compact": self.compact_model, "midsize": self.midsize_model}


settings = Settings()
