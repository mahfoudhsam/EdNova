"""(Re)index the exercise bank into the vector store in a few batched calls.

    cd backend && python ../tools/index_content.py [--reset]
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import db, rag  # noqa: E402
from app.llm_gateway import get_gateway  # noqa: E402


async def main() -> None:
    if "--reset" in sys.argv:
        db.execute("DELETE FROM chunks")
    n = await rag.index_all(get_gateway())
    print(f"Indexed {n} chunks. Store now holds {rag.store.count()} chunks.")


if __name__ == "__main__":
    asyncio.run(main())
