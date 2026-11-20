"""Typed command previews reuse wardrobe semantics and preserve the actor on rejection."""

from copy import deepcopy

import pytest

from backend.engine.clothing.changes import preview
from backend.engine.clothing.context import actor_records
from tests.observable_state_support import profile, world


def actor():
    host, rows = world()
    return actor_records(host, rows)["npc"]


def test_partial_then_full_wear_and_removal_conserve_identity_and_other_layers():
    initial = actor()
    original = deepcopy(initial)
    shifted = preview(initial, "COAT", "adjust", ["arms"], detailed=False)
    assert initial == original
    worn = {row["item_id"]: row for row in shifted["visual_profile"]["worn"]}
    assert worn["COAT"]["uncovered_regions"] == ["arms"]
    assert "LINING" in worn
    restored = preview(shifted, "COAT", "wear", [], detailed=False)
    assert (
        next(row for row in restored["visual_profile"]["worn"] if row["item_id"] == "COAT")[
            "uncovered_regions"
        ]
        == []
    )
    removed = preview(restored, "COAT", "remove", [], detailed=False)
    assert {row["item_id"] for row in removed["visual_profile"]["worn"]} == {"LINING"}
    assert removed["inventory"] == original["inventory"]
    assert removed["resolved_inventory"] == original["resolved_inventory"]


@pytest.mark.parametrize("operation,regions", [("adjust", ["legs"]), ("remove", []), ("wear", [])])
def test_invalid_or_unowned_changes_do_not_mutate_the_previous_actor(operation, regions):
    original = actor()
    before = deepcopy(original)
    identifier = "COAT" if operation == "adjust" else "OTHER_COAT"
    with pytest.raises(ValueError):
        preview(original, identifier, operation, regions, detailed=False)
    assert original == before


def test_adjustment_does_not_turn_a_carried_item_into_a_worn_garment():
    original = actor()
    original["visual_profile"] = profile("LINING")
    with pytest.raises(ValueError, match="not currently worn"):
        preview(original, "COAT", "adjust", ["arms"], detailed=False)


def test_removal_keeps_a_raw_inventory_reference_without_adding_a_second_copy():
    original = actor()
    original["inventory"] = [
        "COAT",
        *[
            row
            for row in original["inventory"]
            if (row.get("id") if isinstance(row, dict) else row) != "COAT"
        ],
    ]
    changed = preview(original, "COAT", "remove", [], detailed=False)
    ids = [row.get("id") if isinstance(row, dict) else row for row in changed["inventory"]]
    assert ids.count("COAT") == 1
    assert "COAT" not in {row["item_id"] for row in changed["visual_profile"]["worn"]}
