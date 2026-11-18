"""Positive carried knowledge changes only the selected garment's assessment."""

from copy import deepcopy

import pytest

from backend.engine.narrated_items.actor_items import receive
from tests.test_narrated_items import fixtures

COAT = {
    "id": "COAT",
    "name": "Coat",
    "clothing": {"layer": 2, "coverage": ["torso", "arms"]},
}


@pytest.mark.parametrize("disposition", ["held", "carried"])
@pytest.mark.parametrize("partial", [False, True])
def test_new_carried_garment_keeps_existing_profile_shape_and_provenance(disposition, partial):
    actor = fixtures()[0]["NPC"]
    actor["visual_profile"]["worn"][0]["source"] = {
        "content_hash": "a" * 64,
        "evidence": "Anna wears her blue shirt.",
        "source_message_id": "earlier-reply",
    }
    if partial:
        actor["inventory"].append({**COAT, "id": "OTHER_COAT"})
        actor["resolved_inventory"].append({**COAT, "id": "OTHER_COAT"})
        actor["visual_profile"].update(
            wear_assessment_complete=False, unassessed_wear_item_ids=["OTHER_COAT"]
        )
    before = deepcopy(actor["visual_profile"])

    receive(actor, COAT, disposition, detailed=True)

    assert actor["visual_profile"] == before
    assert actor["inventory"][-1] == COAT


def test_existing_unassessed_garment_records_its_new_carried_knowledge():
    actor = fixtures()[0]["NPC"]
    actor["inventory"].extend([deepcopy(COAT), {**COAT, "id": "OTHER_COAT"}])
    actor["resolved_inventory"] = deepcopy(actor["inventory"])
    actor["visual_profile"].update(
        wear_assessment_complete=False, unassessed_wear_item_ids=["COAT", "OTHER_COAT"]
    )

    receive(actor, COAT, "carried", detailed=True)

    assert actor["visual_profile"]["unassessed_wear_item_ids"] == ["OTHER_COAT"]
    assert actor["visual_profile"]["wear_assessment_complete"] is False
    assert [row["item_id"] for row in actor["visual_profile"]["worn"]] == ["SHIRT"]
