"""Shared fixtures.

Nothing here makes a network call. `fake_gemini` in particular is what
keeps the whole suite hermetic and fast (Google's "small test" definition:
single process, no sleeps, no real backends) - see README Testing section.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from app.config import Settings


@pytest.fixture
def settings() -> Settings:
    """A deterministic Settings instance, independent of the real .env."""
    return Settings(
        gemini_api_key="test-key-not-real",
        gemini_model="gemini-2.5-flash",
        gemini_temperature=0.4,
        gemini_max_output_tokens=600,
        gemini_timeout_seconds=5.0,
        gemini_max_retries=2,
        rate_limit_per_minute=20,
        max_message_chars=800,
    )


class FakeGeminiClient:
    """Drop-in replacement for GeminiClient that never touches the network.

    Configurable with a canned reply (split into word-ish chunks, the way
    real streaming arrives) or a canned exception to simulate failure.
    """

    def __init__(self, reply: str = "This is a fake reply for testing.", raises: Exception | None = None):
        self.reply = reply
        self.raises = raises
        self.calls: list[tuple[str, str]] = []

    async def stream_reply(self, prompt: str, system_instruction: str) -> AsyncIterator[str]:
        """Yields the canned reply word-by-word, or raises the canned error.

        Records every call in `self.calls` so tests can assert on exactly
        what prompt and system instruction the caller constructed.
        """
        self.calls.append((prompt, system_instruction))
        if self.raises:
            raise self.raises
        for word in self.reply.split(" "):
            yield word + " "


@pytest.fixture
def fake_gemini() -> FakeGeminiClient:
    """A fresh FakeGeminiClient with default canned output for each test."""
    return FakeGeminiClient()
