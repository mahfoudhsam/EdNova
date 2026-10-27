"""Retrieval resilience: embeddings failures must degrade to keyword search,
never break the explain step outright (rag.py's "degrade, don't fail")."""
import pytest

import mock_llm
from app import rag

pytestmark = pytest.mark.asyncio


async def test_search_uses_vectors_when_embeddings_are_healthy(gateway):
    await rag.index_all(gateway)
    chunks = await rag.search(gateway, "dérivée", exercise_id="deriv-01", k=3)
    assert chunks


async def test_search_degrades_to_keyword_search_on_a_sustained_embeddings_outage(gateway):
    await rag.index_all(gateway)
    mock_llm.chaos["embed_down"] = True
    # Must not raise: the GatewayError from embed() is caught and keyword
    # search takes over, so the explain step still gets usable context.
    chunks = await rag.search(gateway, "dérivée", exercise_id="deriv-01", k=3)
    assert chunks
