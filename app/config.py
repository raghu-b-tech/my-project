"""Application configuration.

Every runtime setting is read from the environment so that no secret or
environment-specific value is ever hardcoded in source. See `.env.example`
for the full list of supported variables and their defaults.
"""

from __future__ import annotations

import functools
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()  # No-op in production if a real environment is already set.


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    """Immutable, validated application settings.

    Attributes:
        gemini_api_key: Secret key for the Gemini API. Never logged.
        gemini_model: Model ID used for chat completions.
        gemini_temperature: Sampling temperature (0.0 - 1.0).
        gemini_max_output_tokens: Hard cap on generated tokens per reply.
        gemini_timeout_seconds: Per-request timeout to the Gemini API.
        gemini_max_retries: Max retry attempts on transient failures.
        rate_limit_per_minute: Max chat requests allowed per client per
            minute, enforced in-process to bound API spend and abuse.
        max_message_chars: Hard cap on incoming user message length.
    """

    gemini_api_key: str
    gemini_model: str
    gemini_temperature: float
    gemini_max_output_tokens: int
    gemini_timeout_seconds: float
    gemini_max_retries: int
    rate_limit_per_minute: int
    max_message_chars: int


def _require(name: str) -> str:
    """Reads a required environment variable or raises ConfigError.

    Args:
        name: Environment variable name.

    Returns:
        The variable's value.

    Raises:
        ConfigError: If the variable is unset or empty.
    """
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(
            f"Missing required environment variable: {name}. "
            "Copy .env.example to .env and fill it in."
        )
    return value


def _optional_float(name: str, default: float) -> float:
    """Reads an optional float environment variable.

    Args:
        name: Environment variable name.
        default: Value to use when the variable is unset or empty.

    Returns:
        The parsed float, or `default`.
    """
    raw = os.environ.get(name)
    return float(raw) if raw else default


def _optional_int(name: str, default: int) -> int:
    """Reads an optional integer environment variable.

    Args:
        name: Environment variable name.
        default: Value to use when the variable is unset or empty.

    Returns:
        The parsed int, or `default`.
    """
    raw = os.environ.get(name)
    return int(raw) if raw else default


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Builds and caches the process-wide Settings instance.

    Cached with lru_cache so environment parsing happens once per process,
    not on every request (a small but real efficiency win under load).

    Returns:
        The validated Settings singleton.

    Raises:
        ConfigError: If GEMINI_API_KEY is missing.
    """
    return Settings(
        gemini_api_key=_require("GEMINI_API_KEY"),
        gemini_model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
        gemini_temperature=_optional_float("GEMINI_TEMPERATURE", 0.4),
        gemini_max_output_tokens=_optional_int("GEMINI_MAX_OUTPUT_TOKENS", 600),
        gemini_timeout_seconds=_optional_float("GEMINI_TIMEOUT_SECONDS", 12.0),
        gemini_max_retries=_optional_int("GEMINI_MAX_RETRIES", 2),
        rate_limit_per_minute=_optional_int("RATE_LIMIT_PER_MINUTE", 20),
        max_message_chars=_optional_int("MAX_MESSAGE_CHARS", 800),
    )
