"""API-level tests using FastAPI's TestClient.

Medium tests in Google's sizing sense: a real ASGI app boots in-process,
but `GeminiClient` is monkeypatched to `FakeGeminiClient` first, so there
is still no real network call and no real API key needed. This is the
layer that catches wiring bugs (routes, status codes, SSE framing) that
the smaller unit tests below it can't see.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import FakeGeminiClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")

    from app.config import get_settings

    get_settings.cache_clear()

    import app.main as main_module

    monkeypatch.setattr(main_module, "GeminiClient", lambda settings: FakeGeminiClient())

    with TestClient(main_module.app) as test_client:
        yield test_client

    get_settings.cache_clear()


def test_healthz(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["venue"] == "MetLife Stadium"


def test_index_serves_html(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_chat_rejects_empty_message(client: TestClient) -> None:
    response = client.post("/api/chat", json={"message": ""})
    assert response.status_code == 422  # pydantic min_length=1 catches this


def test_chat_streams_meta_and_token_events(client: TestClient) -> None:
    response = client.post(
        "/api/chat",
        json={
            "message": "Where is the nearest accessible restroom?",
            "language": "en",
            "current_zone": "gate-g",
            "accessibility_needs": ["wheelchair"],
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    body = response.text
    assert "event: meta" in body
    assert "event: token" in body
    assert "event: done" in body
    assert "NAVIGATE" in body


def test_chat_rate_limit_returns_429_after_threshold(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "2")

    from app.config import get_settings

    get_settings.cache_clear()

    import app.main as main_module

    monkeypatch.setattr(main_module, "GeminiClient", lambda settings: FakeGeminiClient())

    with TestClient(main_module.app) as test_client:
        payload = {"message": "hi", "current_zone": "gate-c"}
        assert test_client.post("/api/chat", json=payload).status_code == 200
        assert test_client.post("/api/chat", json=payload).status_code == 200
        assert test_client.post("/api/chat", json=payload).status_code == 429

    get_settings.cache_clear()
