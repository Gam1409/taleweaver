"""The live item producer must enforce the same garment classification as recovery."""

import pytest

from tests.test_narrated_items import action, fixtures, run


def garment(name="Red briefs"):
    return action(
        item_id=None,
        source_owner="NPC",
        destination_owner="NPC",
        evidence="Anna places the garment in her bag.",
        new_item={
            "name": name,
            "description": "A plain cotton garment.",
            "kind": "clothing",
            "clothing": {"layer": 0, "coverage": ["pelvis"], "opaque": True, "underwear": False},
            "wearable_slots": ["Legs"],
        },
    )


@pytest.mark.parametrize("detailed,age", [(False, 30), (True, 17), (True, None), (True, "30")])
def test_live_model_cannot_bypass_clothing_settings_with_a_false_flag(detailed, age):
    actors, snapshot = fixtures()
    actors["NPC"]["age_years"] = age
    changed, accepted, rejected = run([garment()], actors, snapshot, detailed=detailed)
    assert rejected and not accepted and changed == actors


@pytest.mark.parametrize("name", ["Red briefs", "Красные трусики", "Silk bra"])
def test_allowed_live_clothing_persists_the_corrected_flag(name):
    changed, accepted, rejected = run([garment(name)], detailed=True)
    assert not rejected and len(accepted) == 1
    assert accepted[0]["item"]["clothing"]["underwear"] is True
    assert changed["NPC"]["inventory"][-1]["clothing"]["underwear"] is True


def test_pelvis_coverage_alone_does_not_make_trousers_underwear():
    _, accepted, rejected = run([garment("Cotton trousers")], detailed=False)
    assert not rejected and accepted[0]["item"]["clothing"]["underwear"] is False
