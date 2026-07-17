"""Small tests for app.gemini_client.

Deliberately scoped to the pure, deterministic pieces: retry classification
and backoff timing. `_connect_with_retry` itself calls a real SDK client
and is exercised by the live smoke test described in the README instead of
mocked here - constructing fake SDK exception objects with the right
internal shape would couple this suite to google-genai internals that
aren't part of its public contract.
"""

from __future__ import annotations

from app.config import Settings
from app.gemini_client import GeminiClient, _backoff_seconds, _is_retryable


class TestIsRetryable:
    """Which failures are worth a retry vs. a fast, honest failure."""

    def test_rate_limit_and_server_errors_are_retryable(self) -> None:
        for code in (429, 500, 502, 503, 504):
            assert _is_retryable(code) is True, f"expected {code} to be retryable"

    def test_client_errors_are_not_retryable(self) -> None:
        for code in (400, 401, 403, 404):
            assert _is_retryable(code) is False, f"expected {code} to NOT be retryable"

    def test_missing_status_code_is_not_retryable(self) -> None:
        assert _is_retryable(None) is False


class TestBackoffSeconds:
    """Bounds on the jittered exponential backoff delay."""

    def test_delay_grows_with_attempt_number(self) -> None:
        # Compare the *ceiling* each attempt can reach, since the actual
        # value is randomized (full jitter) - check many samples per attempt.
        maxima = [max(_backoff_seconds(attempt, base=0.5, cap=8.0) for _ in range(200)) for attempt in range(5)]
        assert maxima == sorted(maxima), "later attempts should allow larger delays"

    def test_delay_never_exceeds_the_cap(self) -> None:
        samples = [_backoff_seconds(attempt=10, base=0.5, cap=8.0) for _ in range(500)]
        assert max(samples) <= 8.0

    def test_delay_is_never_negative(self) -> None:
        samples = [_backoff_seconds(attempt=0, base=0.5, cap=8.0) for _ in range(500)]
        assert min(samples) >= 0.0


class TestGeminiClientConfig:
    """The generation config actually sent along with each request."""

    def test_config_applies_settings_and_safety(self, settings: Settings) -> None:
        client = GeminiClient(settings)
        config = client._config("You are FanPath.")

        assert config.system_instruction == "You are FanPath."
        assert config.temperature == settings.gemini_temperature
        assert config.max_output_tokens == settings.gemini_max_output_tokens
        assert len(config.safety_settings) == 4
