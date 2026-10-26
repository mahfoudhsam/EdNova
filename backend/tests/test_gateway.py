"""The error contract from the API guide, tested against the mock server."""
import time

import pytest

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
