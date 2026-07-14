"""Small tests for app.knowledge_base - pure data lookups, no network, no model."""

from __future__ import annotations

from app import knowledge_base as kb


def test_venue_metadata_loads() -> None:
    assert kb.venue_name() == "MetLife Stadium"
    assert "New Jersey" in kb.venue_city()


def test_find_amenities_filters_by_accessibility() -> None:
    accessible = kb.find_amenities("restroom", accessible_only=True)
    assert accessible, "expected at least one accessible restroom in the demo dataset"
    assert all(a.wheelchair_accessible for a in accessible)


def test_find_amenities_filters_by_dietary_tag() -> None:
    halal = kb.find_amenities("food", dietary_tag="halal")
    assert len(halal) == 1
    assert "halal" in halal[0].dietary_tags


def test_find_amenities_returns_empty_list_for_no_match() -> None:
    result = kb.find_amenities("food", dietary_tag="kosher")
    assert result == []


def test_nearest_amenity_skips_inaccessible_options_when_required() -> None:
    # gate-g's own restroom (rr-g1) is NOT wheelchair accessible in the
    # demo dataset - nearest_amenity must skip it and route further out.
    nearest = kb.nearest_amenity("gate-g", "restroom", accessible_only=True)
    assert nearest is not None
    assert nearest.id != "rr-g1"
    assert nearest.wheelchair_accessible


def test_nearest_amenity_returns_none_when_unreachable() -> None:
    result = kb.nearest_amenity("nonexistent-zone", "restroom")
    assert result is None


def test_gate_status_known_and_unknown_gates() -> None:
    status = kb.gate_status("gate-e")
    assert status is not None
    assert status.wait_minutes > 0

    assert kb.gate_status("gate-does-not-exist") is None


def test_least_congested_gate_picks_the_minimum() -> None:
    least_busy = kb.least_congested_gate()
    all_waits = [kb.gate_status(gid).wait_minutes for gid in ("gate-a", "gate-c", "gate-e", "gate-g")]
    assert least_busy.wait_minutes == min(all_waits)
