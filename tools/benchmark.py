"""Run the same prompts on both model classes and save a sheet to score by hand.

    cd backend && python ../tools/benchmark.py            # -> benchmark_results.csv

Score each row 1-5 for quality (and for Darija: dialect adherence) in the CSV.
The averages + median latency per class are your evidence for routing.yaml
and for the "why not send everything to mid-size?" jury question.
"""
from __future__ import annotations

import asyncio
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from openai import AsyncOpenAI  # noqa: E402

from app.config import settings  # noqa: E402

PROMPTS = Path(__file__).resolve().parent / "benchmark_prompts.jsonl"
OUT = Path.cwd() / "benchmark_results.csv"
SYSTEM = ("You are EdNova, a study companion for Tunisian learners. Guide with one hint; do not give the final answer. "
          "Reply in the learner's language; for Tunisian Darija keep math terms in French. Max 4 sentences.")


async def main() -> None:
    client = AsyncOpenAI(base_url=settings.base_url, api_key=settings.api_key, max_retries=2,
                         timeout=settings.request_timeout_s)
    rows = [json.loads(l) for l in PROMPTS.read_text(encoding="utf-8").splitlines() if l.strip()]
    out = []
    for i, row in enumerate(rows, 1):
        for cls, model in settings.models.items():
            t0 = time.perf_counter()
            try:
                r = await client.chat.completions.create(
                    model=model, max_tokens=250, temperature=0.3,
                    messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": row["prompt"]}])
                text, err = r.choices[0].message.content, ""
                toks = r.usage.completion_tokens if r.usage else ""
            except Exception as e:
                text, err, toks = "", f"{type(e).__name__}: {e}"[:200], ""
            ms = int((time.perf_counter() - t0) * 1000)
            out.append({"id": row["id"], "category": row["category"], "class": cls, "model": model,
                        "latency_ms": ms, "completion_tokens": toks, "prompt": row["prompt"],
                        "reply": text, "error": err, "score_quality_1_5": "", "score_language_1_5": ""})
            print(f"[{i}/{len(rows)}] {cls:8s} {ms:6d} ms  {row['id']}")
            await asyncio.sleep(0.5)   # be gentle with the shared quota
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    print(f"Saved {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
