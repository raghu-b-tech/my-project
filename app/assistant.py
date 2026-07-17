"""Ties together retrieval (knowledge_base), guardrails (security), and
generation (gemini_client) into one turn of conversation.

Architecture, in one sentence: Python decides *what is true* (deterministic,
fast, fully unit-testable); Gemini decides *how to say it* (personalized,
multilingual, reasoning over the fan's stated context). Routing is a small
keyword classifier rather than a second model call - cheap, instant, and
easy to reason about, which matters because it runs on every single turn.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass

from app import knowledge_base as kb
from app.config import Settings
from app.gemini_client import GeminiClient
from app.security import build_guarded_prompt, sanitize_model_output, sanitize_user_input

#: Used only when the client sends no `current_zone` (e.g. a fan hasn't
#: picked one yet). Gate C is an arbitrary but central starting point in
#: the demo dataset, not a claim about real foot traffic.
_DEFAULT_ZONE = "gate-c"

# (ui_category, keyword pattern, knowledge-base category)
_ROUTES: tuple[tuple[str, re.Pattern[str], kb.Category | None], ...] = (
    ("LIVE", re.compile(r"\b(wait|line|queue|busy|crowd(ed)?|congest)", re.I), None),
    ("NAVIGATE", re.compile(r"\b(restroom|bathroom|toilet|washroom)", re.I), "restroom"),
    ("NAVIGATE", re.compile(r"\b(first aid|medic|injur|hurt)", re.I), "first_aid"),
    ("NAVIGATE", re.compile(r"\b(food|eat|hungry|halal|vegan|vegetarian|snack)", re.I), "food"),
    ("ACCESS", re.compile(r"\b(elevator|lift|wheelchair|ramp)", re.I), "elevator"),
    ("NAVIGATE", re.compile(r"\b(help|desk|guest services|lost|found)", re.I), "guest_services"),
    ("NAVIGATE", re.compile(r"\b(train|transit|bus|parking|rail|shuttle)", re.I), "transit"),
)

_SYSTEM_INSTRUCTION = """\
You are FanPath, a calm and precise wayfinding concierge for fans at {venue} \
in {city} during the FIFA World Cup 2026. You are speaking with a fan whose \
preferred language is "{language}" - always reply in that language, \
regardless of what language the fan's message is written in.

Ground every claim in the <venue_facts> you are given. If the facts don't \
cover the question, say so plainly and suggest the fan ask a Fan Services \
desk - never invent a gate, distance, or amenity that wasn't in the facts.

The fan's stated accessibility needs are: {accessibility_needs}. If any are \
set, actively factor them into your routing advice (e.g. prefer step-free \
routes for "wheelchair", avoid recommending loud/crowded routes for \
"sensory_sensitivity") without being asked to repeat them back.

Keep replies short: 2-4 sentences, concrete, and in plain language a \
stressed fan can skim in a few seconds."""


@dataclass(frozen=True)
class TurnMeta:
    """Small, structured header sent before the streamed reply.

    Powers the UI's status-strip element and is fully unit-testable in
    isolation from anything that touches the network.

    Attributes:
        category: One of "NAVIGATE", "ACCESS", "LIVE", or "GENERAL".
        eta_minutes: Walking time to the matched amenity, if any was found.
    """

    category: str
    eta_minutes: int | None


def classify(message: str) -> tuple[str, kb.Category | None]:
    """Routes a message to a UI category and, if applicable, a KB lookup.

    Args:
        message: Sanitized fan message.

    Returns:
        A (ui_category, knowledge_base_category_or_None) pair. Falls back
        to ("GENERAL", None) when nothing matches.
    """
    for ui_category, pattern, kb_category in _ROUTES:
        if pattern.search(message):
            return ui_category, kb_category
    return "GENERAL", None


def gather_facts(
    kb_category: kb.Category | None,
    current_zone: str | None,
    accessibility_needs: list[str],
) -> tuple[str, int | None]:
    """Retrieves deterministic venue facts relevant to one turn.

    Args:
        kb_category: Category returned by `classify`, or None.
        current_zone: Fan's current zone id, if known.
        accessibility_needs: Tags such as "wheelchair".

    Returns:
        A (facts_text, eta_minutes) pair. `facts_text` is a short block of
        plain-text facts to embed in the guarded prompt; `eta_minutes` is
        the walking time to the nearest match, if one was found.
    """
    zone = current_zone or _DEFAULT_ZONE
    accessible_only = "wheelchair" in accessibility_needs

    if kb_category is None:
        least_busy = kb.least_congested_gate()
        facts = (
            f"Least congested gate right now: {least_busy.gate_id} "
            f"({least_busy.congestion}, ~{least_busy.wait_minutes} min wait)."
        )
        return facts, None

    match = kb.nearest_amenity(zone, kb_category, accessible_only=accessible_only)
    if match is None:
        return f"No {kb_category} amenity found from zone '{zone}'.", None

    minutes = match.minutes_from(zone)
    facts = (
        f"Nearest match: {match.name} (id={match.id}), "
        f"wheelchair_accessible={match.wheelchair_accessible}, "
        f"~{minutes} min walk from '{zone}'."
    )
    return facts, minutes


async def handle_turn(
    settings: Settings,
    gemini: GeminiClient,
    message: str,
    language: str,
    current_zone: str | None,
    accessibility_needs: list[str],
) -> AsyncIterator[TurnMeta | str]:
    """Runs one full conversation turn.

    Yields a single `TurnMeta` first, then a stream of sanitized text
    chunks. Callers (see app/main.py) turn this into Server-Sent Events.

    Args:
        settings: Validated app settings.
        gemini: A GeminiClient instance (injected so tests can substitute a
            fake and never touch the network - see tests/test_assistant.py).
        message: Raw fan message.
        language: Fan's preferred reply language.
        current_zone: Fan's current zone id, if known.
        accessibility_needs: Subset of ACCESSIBILITY_TAGS.

    Yields:
        First a TurnMeta, then str chunks of the assistant's reply.
    """
    sanitized = sanitize_user_input(message, max_chars=settings.max_message_chars)
    ui_category, kb_category = classify(sanitized.text)
    facts, eta_minutes = gather_facts(kb_category, current_zone, accessibility_needs)

    yield TurnMeta(category=ui_category, eta_minutes=eta_minutes)

    system_instruction = _SYSTEM_INSTRUCTION.format(
        venue=kb.venue_name(),
        city=kb.venue_city(),
        language=language,
        accessibility_needs=", ".join(accessibility_needs) or "none stated",
    )
    prompt = build_guarded_prompt(system_instruction, facts, sanitized)

    async for chunk in gemini.stream_reply(prompt, system_instruction):
        yield sanitize_model_output(chunk)
