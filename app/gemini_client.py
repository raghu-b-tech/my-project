"""Thin async wrapper around the Gemini API (google-genai SDK).

Worth being explicit about how this interacts with the SDK itself: the
google-genai client already retries transient errors (timeouts, 429s,
5xx) internally before ever raising to our code. This wrapper is a small
outer layer on top of that, not a replacement for it, so it stays
deliberately thin:

1. GEMINI_MAX_RETRIES defaults to 2, not a large number - the SDK has
   already tried and failed before we see an exception, so stacking many
   more attempts on top mostly just adds worst-case latency for a fan
   waiting on an answer.
2. What this layer adds on top of the SDK default: explicit jitter,
   structured logging of each attempt, and a clean `GeminiUnavailableError`
   with a fan-facing message instead of a raw SDK exception reaching the
   route handler.
3. Retries only wrap the *initial* call. Once tokens start streaming to
   the fan, we don't retry mid-stream - that risks silently duplicating
   text. A failed stream surfaces a clear, honest error instead.

Model name, temperature, and token cap are all config-driven (see
config.py) rather than hardcoded, since Gemini model IDs are versioned and
this project shouldn't need a code change to point at a newer one.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import AsyncIterator

from google import genai
from google.genai import types
from google.genai.errors import APIError

from app.config import Settings

logger = logging.getLogger("fanpath.gemini")

# Errors worth retrying: rate limiting and transient server-side failures.
# Anything else (bad request, auth failure) is a bug or misconfiguration
# and retrying it would just waste the retry budget.
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

_SAFETY_SETTINGS = [
    types.SafetySetting(category=category, threshold="BLOCK_MEDIUM_AND_ABOVE")
    for category in (
        "HARM_CATEGORY_HARASSMENT",
        "HARM_CATEGORY_HATE_SPEECH",
        "HARM_CATEGORY_SEXUALLY_EXPLICIT",
        "HARM_CATEGORY_DANGEROUS_CONTENT",
    )
]


class GeminiUnavailableError(RuntimeError):
    """Raised when the Gemini API fails after exhausting all retries."""


def _backoff_seconds(attempt: int, base: float = 0.5, cap: float = 8.0) -> float:
    """Randomized exponential backoff (full jitter).

    Args:
        attempt: Zero-indexed retry attempt number.
        base: Initial delay in seconds.
        cap: Maximum delay in seconds, so retries never stall the request
            indefinitely even after many attempts.

    Returns:
        Seconds to sleep before the next attempt.
    """
    ceiling = min(cap, base * (2**attempt))
    return random.uniform(0, ceiling)


class GeminiClient:
    """Wraps `google.genai.Client` with retry, timeout, and safety config."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(timeout=int(settings.gemini_timeout_seconds * 1000)),
        )

    def _config(self, system_instruction: str) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=self._settings.gemini_temperature,
            max_output_tokens=self._settings.gemini_max_output_tokens,
            safety_settings=_SAFETY_SETTINGS,
        )

    async def stream_reply(
        self, prompt: str, system_instruction: str
    ) -> AsyncIterator[str]:
        """Streams a reply for one prompt, retrying only the initial connect.

        Args:
            prompt: The fully-assembled, delimiter-guarded prompt (see
                `security.build_guarded_prompt`).
            system_instruction: Persona/behavior instructions for the model.

        Yields:
            Text chunks as they arrive from the model.

        Raises:
            GeminiUnavailableError: If every retry attempt fails.
        """
        stream = await self._connect_with_retry(prompt, system_instruction)
        try:
            async for chunk in stream:
                if chunk.text:
                    yield chunk.text
        except APIError as exc:
            logger.warning("Gemini stream interrupted mid-response: %s", exc)
            raise GeminiUnavailableError(
                "The connection to the assistant dropped partway through. Please try again."
            ) from exc

    async def _connect_with_retry(self, prompt: str, system_instruction: str):
        last_error: Exception | None = None
        for attempt in range(self._settings.gemini_max_retries):
            try:
                return await self._client.aio.models.generate_content_stream(
                    model=self._settings.gemini_model,
                    contents=prompt,
                    config=self._config(system_instruction),
                )
            except APIError as exc:
                last_error = exc
                status = getattr(exc, "code", None)
                if status not in _RETRYABLE_STATUS_CODES:
                    raise GeminiUnavailableError(f"Gemini request failed: {exc}") from exc
                delay = _backoff_seconds(attempt)
                logger.info(
                    "Gemini call failed (status=%s), retry %d/%d in %.2fs",
                    status,
                    attempt + 1,
                    self._settings.gemini_max_retries,
                    delay,
                )
                await asyncio.sleep(delay)

        raise GeminiUnavailableError(
            f"Gemini API unavailable after {self._settings.gemini_max_retries} attempts."
        ) from last_error
