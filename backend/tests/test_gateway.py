"""The error contract from the API guide, tested against the mock server."""
import time
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import APIConnectionError

import mock_llm
from app import metrics
from app.llm_gateway import GatewayError

pytestmark = pytest.mark.asyncio

MSG = [{"role": "system", "content": "You are a test."}, {"role": "user", "content": "hello"}]


async def test_routes_steps_to_the_right_class(gateway):
    hint = await gateway.chat("hint", MSG)
    explain = await gateway.chat("explain", MSG)
    assert hint.model_class == "compact" and hint.model == "mock-compact-1.5b"
    assert explain.model_class == "midsize" and explain.model == "mock-mid-14b"
    s = metrics.summary()
    assert s["calls_by_class"] == {"compact": 1, "midsize": 1}


async def test_quota_headers_are_recorded(gateway):
    await gateway.chat("hint", MSG)
    assert "x-ratelimit-remaining-requests" in gateway.quota.headers


async def test_midsize_503_falls_back_to_compact(gateway):
    mock_llm.chaos["midsize_503"] = True
    events = []

    async def on_status(e):
        events.append(e["kind"])

    res = await gateway.chat("explain", MSG, on_status=on_status)
    assert res.model_class == "compact" and res.fell_back
    assert "midsize_busy" in events
    assert metrics.summary()["errors_by_status"].get("503") == 1


async def test_quota_exhausted_waits_stated_delay_then_succeeds(gateway):
    mock_llm.chaos["quota_until"] = time.time() + 1
    waits = []

    async def on_status(e):
        if e["kind"] == "quota_wait":
            waits.append(e["seconds"])

    t0 = time.perf_counter()
    res = await gateway.chat("hint", MSG, on_status=on_status)
    assert res.text
    assert waits and waits[0] >= 1
    assert time.perf_counter() - t0 >= 0.9


async def test_ceiling_400_shrinks_once(gateway, monkeypatch):
    from app.router import router
    route = router.get("hint")
    monkeypatch.setitem(router._routes, "hint", route.__class__(**{**route.__dict__, "max_tokens": 1500}))
    res = await gateway.chat("hint", MSG)       # 1500 > ceiling 1024 -> 400 -> retried with 750
    assert res.text
    assert metrics.summary()["errors_by_status"].get("400") == 1


async def test_unknown_model_raises_clean_error(gateway, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "compact_model", "does-not-exist")
    with pytest.raises(GatewayError) as e:
        await gateway.chat("hint", MSG)
    assert e.value.user_message


async def test_simulated_chaos_switch(gateway):
    gateway.chaos.midsize_unavailable = True
    res = await gateway.chat("explain", MSG)
    assert res.fell_back and res.model_class == "compact"


async def test_low_quota_paces_down_before_hitting_saturation(gateway):
    """Below the pacing threshold, the gateway proactively uses the fallback
    class for a mid-size step - it never spends a mid-size call only to be
    told the quota is gone."""
    gateway.quota.remaining, gateway.quota.limit = 5, 60   # 5/60 well under the 0.2 default
    events = []

    async def on_status(e):
        events.append(e["kind"])

    res = await gateway.chat("explain", MSG, on_status=on_status)
    assert res.model_class == "compact" and res.fell_back
    assert res.fallback_reason == "pacing"
    assert "pacing" in events


async def test_healthy_quota_does_not_pace_down(gateway):
    gateway.quota.remaining, gateway.quota.limit = 50, 60   # well above the threshold
    res = await gateway.chat("explain", MSG)
    assert res.model_class == "midsize" and not res.fell_back


async def test_quota_headers_feed_remaining_and_limit(gateway):
    await gateway.chat("hint", MSG)
    assert gateway.quota.remaining is not None and gateway.quota.limit is not None


def _embed_rows():
    # metrics.summary()'s errors_by_status deliberately excludes step="embed"
    # rows (it tracks chat-call errors only), so read the raw log instead.
    return [r for r in metrics.recent(50) if r["step"] == "embed"]


async def test_embed_retries_once_then_succeeds_on_a_transient_blip(gateway):
    mock_llm.chaos["embed_fail_once"] = True
    vectors = await gateway.embed(["bonjour tout le monde"])
    assert len(vectors) == 1 and len(vectors[0])
    rows = _embed_rows()
    assert sum(1 for r in rows if r["status"] == 503) == 1   # the one failed attempt, logged
    assert sum(1 for r in rows if r["status"] == 200) == 1   # then the retry succeeded


async def test_embed_gives_up_as_a_clean_gateway_error_on_a_sustained_outage(gateway):
    mock_llm.chaos["embed_down"] = True
    with pytest.raises(GatewayError) as exc:
        await gateway.embed(["bonjour"])
    assert exc.value.user_message
    rows = _embed_rows()
    assert sum(1 for r in rows if r["status"] == 503) == 2   # initial attempt + the one retry


async def test_embed_converts_a_network_error_to_gateway_error(gateway, monkeypatch):
    """A raw SDK network exception must become GatewayError, or rag.search()'s
    `except GatewayError: return keyword_search(...)` never fires and the
    explain step breaks outright on a network blip instead of degrading."""
    req = httpx.Request("POST", "http://mock/v1/embeddings")
    mock_create = AsyncMock(side_effect=APIConnectionError(request=req))
    monkeypatch.setattr(gateway.client.embeddings, "create", mock_create)
    with pytest.raises(GatewayError) as exc:
        await gateway.embed(["bonjour"])
    assert exc.value.user_message
    assert mock_create.call_count == 2   # one retry before giving up
