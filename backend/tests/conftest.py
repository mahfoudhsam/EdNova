"""Tests run the real gateway against the mock server in-process (no network)."""
import os
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))

os.environ.update({
    "EDNOVA_BASE_URL": "http://mock/v1",
    "EDNOVA_API_KEY": "test-key",
    "COMPACT_MODEL": "mock-compact-1.5b",
    "MIDSIZE_MODEL": "mock-mid-14b",
    "EMBEDDING_MODEL": "mock-embed",
    "MAX_RETRY_AFTER_S": "2",
})

import mock_llm  # noqa: E402
from app import db  # noqa: E402
from app.llm_gateway import LLMGateway  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_state(tmp_path):
    db.reset_for_tests(str(tmp_path / "test.sqlite3"))
    mock_llm.chaos.clear()
    mock_llm.chaos.update(mock_llm.DEFAULT_CHAOS, latency_compact=0.0, latency_midsize=0.0)
    mock_llm.bucket.update(tokens=60.0)
    yield


@pytest.fixture
def gateway():
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=mock_llm.app), base_url="http://mock")
    return LLMGateway(http_client=client)
