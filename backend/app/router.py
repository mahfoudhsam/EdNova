"""Routing table: step name -> model class + budgets. Loaded from routing.yaml."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from .config import settings


@dataclass(frozen=True)
class Route:
    step: str
    model_class: str           # "compact" | "midsize"
    max_tokens: int
    temperature: float
    fallback: Optional[str]    # class to fall back to on saturation
    why: str


class Router:
    def __init__(self, path: str | None = None):
        self.path = Path(path or settings.routing_path)
        self._routes: dict[str, Route] = {}
        self.reload()

    def reload(self) -> None:
        data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        routes = {}
        for step, cfg in (data.get("steps") or {}).items():
            cls = cfg.get("class", "compact")
            if cls not in ("compact", "midsize"):
                raise ValueError(f"routing.yaml: step {step!r} has unknown class {cls!r}")
            routes[step] = Route(
                step=step,
                model_class=cls,
                max_tokens=int(cfg.get("max_tokens", 200)),
                temperature=float(cfg.get("temperature", 0.3)),
                fallback=cfg.get("fallback"),
                why=cfg.get("why", ""),
            )
        self._routes = routes

    def get(self, step: str) -> Route:
        if step not in self._routes:
            raise KeyError(f"No route for step {step!r}; add it to routing.yaml")
        return self._routes[step]

    def table(self) -> list[dict]:
        return [r.__dict__ for r in self._routes.values()]


router = Router()
