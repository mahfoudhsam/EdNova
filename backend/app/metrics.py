"""Per-call log + summary.

These mirror the per-team metrics the organisers collect (calls per model,
compact/mid-size split, tokens, repeated requests, quota refusals), so you can
watch your own numbers before the jury does.
"""
from __future__ import annotations

import statistics
import time
from typing import Optional

from . import db


def log_call(
    *,
    step: str,
    model_class: str,
    model: Optional[str] = None,
    status: Optional[int] = None,
    latency_ms: Optional[int] = None,
    prompt_tokens: Optional[int] = None,
    completion_tokens: Optional[int] = None,
    cache_hit: bool = False,
    fell_back: bool = False,
    route_reason: str = "",
    error: Optional[str] = None,
) -> None:
    # Never log message content or the API key: metadata only.
    db.execute(
        """INSERT INTO calls (ts, step, model_class, model, status, latency_ms,
               prompt_tokens, completion_tokens, cache_hit, fell_back, route_reason, error)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (time.time(), step, model_class, model, status, latency_ms, prompt_tokens,
         completion_tokens, int(cache_hit), int(fell_back), route_reason[:200],
         (error or "")[:300] or None),
    )


def summary(since_s: float | None = None) -> dict:
    where, params = "", ()
    if since_s:
        where, params = "WHERE ts >= ?", (time.time() - since_s,)
    rows = db.query(f"SELECT * FROM calls {where} ORDER BY ts", params)

    model_calls = [r for r in rows if r["model_class"] in ("compact", "midsize") and r["step"] != "embed"]
    ok_calls = [r for r in model_calls if r["status"] == 200]
    by_class = {"compact": 0, "midsize": 0}
    for r in ok_calls:
        by_class[r["model_class"]] += 1
    total_ok = sum(by_class.values()) or 1

    lat: dict[str, list[int]] = {"compact": [], "midsize": []}
    for r in ok_calls:
        if r["latency_ms"] is not None:
            lat[r["model_class"]].append(r["latency_ms"])

    by_step: dict[str, dict] = {}
    for r in ok_calls:
        s = by_step.setdefault(r["step"], {"compact": 0, "midsize": 0})
        s[r["model_class"]] += 1

    errors: dict[str, int] = {}
    for r in model_calls:
        if r["status"] != 200:
            errors[str(r["status"])] = errors.get(str(r["status"]), 0) + 1

    cache_hits = sum(1 for r in rows if r["cache_hit"])
    answers = cache_hits + sum(1 for r in ok_calls if r["step"] in ("hint", "explain", "chat"))

    return {
        "calls_ok": len(ok_calls),
        "calls_by_class": by_class,
        "compact_share": round(by_class["compact"] / total_ok, 3),
        "calls_by_step": by_step,
        "embedding_calls": sum(1 for r in rows if r["step"] == "embed" and r["status"] == 200),
        "tokens_in": sum(r["prompt_tokens"] or 0 for r in ok_calls),
        "tokens_out": sum(r["completion_tokens"] or 0 for r in ok_calls),
        "median_latency_ms": {k: (int(statistics.median(v)) if v else None) for k, v in lat.items()},
        "cache_hits": cache_hits,
        "cache_hit_rate": round(cache_hits / answers, 3) if answers else 0.0,
        "fallbacks": sum(1 for r in rows if r["fell_back"]),
        "errors_by_status": errors,
    }


def recent(limit: int = 50) -> list[dict]:
    rows = db.query("SELECT * FROM calls ORDER BY id DESC LIMIT ?", (limit,))
    return [dict(r) for r in rows]
