"""Loads the exercise bank (content/exercises.json) and prompt templates."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from string import Template

from .config import settings


@lru_cache(maxsize=1)
def bank() -> dict:
    return json.loads(Path(settings.content_path).read_text(encoding="utf-8"))


def exercises() -> list[dict]:
    return bank()["exercises"]


def exercise(ex_id: str) -> dict:
    for ex in exercises():
        if ex["id"] == ex_id:
            return ex
    raise KeyError(ex_id)


def glossary() -> list[dict]:
    return bank().get("glossary", [])


def public_exercise(ex: dict) -> dict:
    """What the browser may see: statement and step goals, never the worked solution."""
    return {
        "id": ex["id"],
        "title": ex["title"],
        "skills": ex.get("skills", []),
        "statement": ex["statement"],
        "steps": [{"goal": s["goal"]} for s in ex["steps"]],
    }


@lru_cache(maxsize=None)
def _template(name: str) -> Template:
    return Template((Path(settings.prompts_dir) / f"{name}.txt").read_text(encoding="utf-8"))


def prompt(name: str, **values) -> str:
    return _template(name).safe_substitute(**{k: str(v) for k, v in values.items()})
