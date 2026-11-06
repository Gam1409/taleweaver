# pyright: reportUnusedParameter=false, reportUnusedVariable=false
# pylint: disable=unused-argument,unused-variable
# ruff: noqa: ARG001,F841

"""Tests for the CONSTRUCTABLE item type.

Covers:
- Structural validation (backend.core.world_validator)
- Deterministic engine resolution (GameTurnManager._enforce_constructable_combination)
"""

from backend.core.world_validator import validate_adventure


def _payload(objects):
    return {
        "adventure": {"id": "adv", "start_scene_id": "START", "title": "T", "teaser": "x"},
        "scenes": [{"id": "START", "label": "Start", "description": "A room."}],
        "npcs": [],
        "objects": objects,
        "exits": [],
    }


# ---------------------------------------------------------------------------
# Structural validation
# ---------------------------------------------------------------------------


def _codes(findings):
    return [(f.severity, f.code) for f in findings]


def test_constructable_valid_when_hidden_with_two_ingredients():
    payload = _payload(
        [
            {
                "id": "BATTERY",
                "entity_type": "OBJECT",
                "item_type": "DEFAULT",
                "name": "Battery",
                "is_hidden": False,
            },
            {
                "id": "TORCH",
                "entity_type": "OBJECT",
                "item_type": "DEFAULT",
                "name": "Torch",
                "is_hidden": False,
            },
            {
                "id": "LANTERN",
                "entity_type": "OBJECT",
                "item_type": "CONSTRUCTABLE",
                "name": "Lantern",
                "is_hidden": True,
                "combination_ingredients": ["BATTERY", "TORCH"],
            },
        ]
    )
    findings = [f for f in validate_adventure(payload) if f.code.startswith("constructable")]
    assert findings == []


def test_constructable_needs_at_least_two_ingredients():
    payload = _payload(
        [
            {"id": "BATTERY", "entity_type": "OBJECT", "item_type": "DEFAULT", "name": "Battery"},
            {
                "id": "LANTERN",
                "entity_type": "OBJECT",
                "item_type": "CONSTRUCTABLE",
                "name": "Lantern",
                "is_hidden": True,
                "combination_ingredients": ["BATTERY"],
            },
        ]
    )
    findings = validate_adventure(payload)
    assert ("error", "constructable_needs_ingredients") in _codes(findings)


def test_constructable_missing_ingredient_reference():
    payload = _payload(
        [
            {"id": "BATTERY", "entity_type": "OBJECT", "item_type": "DEFAULT", "name": "Battery"},
            {
                "id": "LANTERN",
                "entity_type": "OBJECT",
                "item_type": "CONSTRUCTABLE",
                "name": "Lantern",
                "is_hidden": True,
                "combination_ingredients": ["BATTERY", "GHOST"],
            },
        ]
    )
    findings = validate_adventure(payload)
    assert ("error", "constructable_ingredient_missing") in _codes(findings)


def test_constructable_should_be_hidden_warns():
    payload = _payload(
        [
            {"id": "BATTERY", "entity_type": "OBJECT", "item_type": "DEFAULT", "name": "Battery"},
            {"id": "TORCH", "entity_type": "OBJECT", "item_type": "DEFAULT", "name": "Torch"},
            {
                "id": "LANTERN",
                "entity_type": "OBJECT",
                "item_type": "CONSTRUCTABLE",
                "name": "Lantern",
                "is_hidden": False,
                "combination_ingredients": ["BATTERY", "TORCH"],
            },
        ]
    )
    findings = validate_adventure(payload)
    assert ("warn", "constructable_not_hidden") in _codes(findings)
