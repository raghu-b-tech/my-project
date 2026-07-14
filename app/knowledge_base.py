"""Deterministic venue facts, kept separate from the language model on purpose.

Gate locations, walking times, and accessibility flags don't need an LLM to
look up - they need a dictionary lookup. Routing every question through
Gemini would be slower, costlier, and harder to test than it needs to be.
So this module answers the "what/where" questions directly; the model's job
(see assistant.py) is only to reason over these facts in natural, personal,
multilingual language. Swap `_load_venue` to call a real facilities API and
nothing above this module has to change.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

_DATA_PATH = Path(__file__).parent / "data" / "venue_metlife.json"

Category = Literal[
    "restroom", "first_aid", "food", "elevator", "guest_services", "transit"
]


@dataclass(frozen=True)
class Amenity:
    """A single point of interest inside the venue."""

    id: str
    category: str
    zone_id: str
    name: str
    wheelchair_accessible: bool
    dietary_tags: tuple[str, ...]
    walking_minutes: dict[str, int]

    def minutes_from(self, zone_id: str) -> int | None:
        return self.walking_minutes.get(zone_id)


@dataclass(frozen=True)
class GateStatus:
    """Simulated live congestion for one gate.

    In production this would be populated from turnstile / crowd-sensor
    telemetry on a short polling interval. Here it's fixed demo data, and
    that's disclosed - see README "Assumptions".
    """

    gate_id: str
    congestion: str
    wait_minutes: int


class VenueNotLoadedError(RuntimeError):
    """Raised when venue data is missing or malformed."""


@lru_cache(maxsize=1)
def _load_raw() -> dict:
    try:
        with _DATA_PATH.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise VenueNotLoadedError(f"Could not load venue data from {_DATA_PATH}") from exc


def _to_amenity(raw: dict) -> Amenity:
    return Amenity(
        id=raw["id"],
        category=raw["category"],
        zone_id=raw["zone_id"],
        name=raw["name"],
        wheelchair_accessible=bool(raw.get("wheelchair_accessible", False)),
        dietary_tags=tuple(raw.get("dietary_tags", ())),
        walking_minutes=dict(raw.get("walking_minutes", {})),
    )


def venue_name() -> str:
    return _load_raw()["name"]


def venue_city() -> str:
    return _load_raw()["city"]


def list_zones() -> list[dict]:
    return list(_load_raw()["zones"])


def find_amenities(
    category: Category,
    accessible_only: bool = False,
    dietary_tag: str | None = None,
) -> list[Amenity]:
    """Filters amenities by category and optional accessibility/diet needs.

    Args:
        category: Amenity category, e.g. "restroom" or "food".
        accessible_only: If True, only return wheelchair-accessible results.
        dietary_tag: If set, only return food amenities carrying this tag
            (e.g. "halal", "vegan"). Ignored for non-food categories.

    Returns:
        Matching amenities, in dataset order (empty list if none match).
    """
    amenities = [_to_amenity(a) for a in _load_raw()["amenities"] if a["category"] == category]
    if accessible_only:
        amenities = [a for a in amenities if a.wheelchair_accessible]
    if dietary_tag:
        amenities = [a for a in amenities if dietary_tag.lower() in a.dietary_tags]
    return amenities


def nearest_amenity(
    from_zone_id: str,
    category: Category,
    accessible_only: bool = False,
    dietary_tag: str | None = None,
) -> Amenity | None:
    """Finds the walking-time-nearest amenity of a category from a zone.

    Args:
        from_zone_id: The fan's current zone, e.g. "gate-c".
        category: Amenity category to search for.
        accessible_only: Restrict to wheelchair-accessible amenities.
        dietary_tag: Restrict food results to a dietary tag.

    Returns:
        The closest matching Amenity, or None if nothing matches or no
        walking-time entry exists for `from_zone_id`.
    """
    candidates = find_amenities(category, accessible_only, dietary_tag)
    reachable = [a for a in candidates if a.minutes_from(from_zone_id) is not None]
    if not reachable:
        return None
    return min(reachable, key=lambda a: a.minutes_from(from_zone_id))


def gate_status(gate_id: str) -> GateStatus | None:
    """Looks up simulated live congestion for a gate.

    Args:
        gate_id: Gate zone id, e.g. "gate-e".

    Returns:
        A GateStatus, or None if the gate id is unknown.
    """
    raw = _load_raw()["gate_status"].get(gate_id)
    if raw is None:
        return None
    return GateStatus(gate_id=gate_id, congestion=raw["congestion"], wait_minutes=raw["wait_minutes"])


def least_congested_gate() -> GateStatus:
    """Returns the gate with the shortest current simulated wait."""
    all_status = [gate_status(gid) for gid in _load_raw()["gate_status"]]
    return min((s for s in all_status if s is not None), key=lambda s: s.wait_minutes)
