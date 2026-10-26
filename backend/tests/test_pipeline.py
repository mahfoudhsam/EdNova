"""End-to-end pipeline: rules, cache, triage, routing, RAG, fallback."""
import pytest

import mock_llm
from app import metrics, rag
from app.pipeline import handle_message
from app.rooms import Room

pytestmark = pytest.mark.asyncio


async def noop(_):
    pass


def room():
    return Room(id="TEST", exercise_id="deriv-01")


async def test_greeting_uses_no_model(gateway):
    r = await handle_message(gateway, room(), "salam", noop)
    assert r["model_class"] == "rule"
    assert metrics.summary()["calls_ok"] == 0


async def test_stuck_learner_gets_compact_hint(gateway):
    rm = room()
    r = await handle_message(gateway, rm, "je bloque sur la première étape", noop)
    assert r["step"] == "hint" and r["model_class"] == "compact"
    assert rm.hint_level == 1


async def test_why_question_goes_to_midsize_with_rag(gateway):
    await rag.index_all(gateway)
    r = await handle_message(gateway, room(), "pourquoi la dérivée de 2 est 0 ?", noop)
    assert r["step"] == "explain" and r["model_class"] == "midsize"


async def test_identical_question_is_served_from_cache(gateway):
    rm = room()
    await handle_message(gateway, rm, "pourquoi la dérivée de 2 est 0 ?", noop)
    before = metrics.summary()["calls_ok"]
    r = await handle_message(gateway, rm, "Pourquoi la dérivée de 2 est 0", noop)
    assert r["cached"] is True
    assert metrics.summary()["calls_ok"] == before


async def test_fallback_answer_is_not_cached(gateway):
    mock_llm.chaos["midsize_503"] = True
    rm = room()
    r1 = await handle_message(gateway, rm, "explique-moi pourquoi", noop)
    assert r1["fell_back"] and r1["model_class"] == "compact"
    mock_llm.chaos["midsize_503"] = False
    r2 = await handle_message(gateway, rm, "explique-moi pourquoi", noop)
    assert not r2["cached"] and r2["model_class"] == "midsize"


async def test_darija_is_detected(gateway):
    r = await handle_message(gateway, room(), "chnowa ma3neha dérivée? ma fhemt chay", noop)
    assert r["language"] == "darija_latin"


async def test_hint_level_caps_at_top_rung_and_cache_is_reused(gateway):
    """room.hint_level feeds the cache key, so it must stop climbing once the
    hint prompt's top rung (2) is reached - otherwise every further hint
    request mints a fresh, never-reused cache key forever."""
    rm = room()
    for _ in range(5):
        r = await handle_message(gateway, rm, "aide-moi", noop)
        assert r["step"] == "hint"
    assert rm.hint_level == 2          # capped, not still climbing after 5 asks

    before = metrics.summary()["calls_ok"]
    r = await handle_message(gateway, rm, "aide-moi", noop)
    assert r["cached"] is True         # same text at the (now stable) top rung -> cache hit
    assert metrics.summary()["calls_ok"] == before
