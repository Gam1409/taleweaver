"""Partial placement and ordered item transitions retain one canonical identity."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.engine.narrated_items.schema import ItemAction
from backend.engine.visual_novel.continuity import PLAYER
from tests.test_narrated_items import action, fixtures, run


def partial(**changes):
    return action(
        source_owner="NPC",
        destination_owner="NPC",
        disposition="worn",
        evidence="Anna raises her blue shirt above her waist.",
        uncovered_regions=["torso"],
        **changes,
    )


def test_partial_removal_keeps_garment_owned_and_worn():
    actors, snapshot = fixtures()
    changed, accepted, errors = run([partial()], actors, snapshot)
    assert not errors and len(accepted) == 1
    assert changed["NPC"]["inventory"] == actors["NPC"]["inventory"]
    assert changed["NPC"]["visual_profile"]["worn"] == [
        {"item_id": "SHIRT", "uncovered_regions": ["torso"]}
    ]
    assert changed[PLAYER] == actors[PLAYER]


def test_explicit_normal_coverage_restores_only_this_garment():
    actors, snapshot = fixtures()
    actors["NPC"]["visual_profile"]["worn"][0]["uncovered_regions"] = ["torso"]
    change = partial().model_copy(
        update={"uncovered_regions": [], "evidence": "Anna lowers her shirt again."}
    )
    changed, accepted, errors = run([change], actors, snapshot)
    assert not errors and accepted
    assert changed["NPC"]["visual_profile"]["worn"][0]["uncovered_regions"] == []


def test_omitted_placement_does_not_restore_existing_coverage():
    actors, snapshot = fixtures()
    actors["NPC"]["visual_profile"]["worn"][0]["uncovered_regions"] = ["torso"]
    change = action(
        destination_owner="NPC", disposition="worn", evidence="Anna is still wearing the shirt."
    )
    changed, _, errors = run([change], actors, snapshot)
    assert not errors
    assert changed["NPC"]["visual_profile"]["worn"][0]["uncovered_regions"] == ["torso"]


def test_partial_placement_outside_garment_coverage_is_atomic():
    actors, snapshot = fixtures()
    change = partial().model_copy(update={"uncovered_regions": ["pelvis"]})
    changed, accepted, errors = run([change], actors, snapshot)
    assert errors and not accepted and changed == actors


@pytest.mark.parametrize("disposition", ["carried", "held"])
def test_partial_placement_cannot_mean_fully_removed(disposition):
    raw = action(disposition=disposition).model_dump()
    with pytest.raises(ValidationError):
        ItemAction.model_validate({**raw, "uncovered_regions": ["torso"]})


def chain():
    return [
        action(destination_owner="NPC", evidence="Anna removes her blue shirt."),
        action(evidence="Anna hands the same blue shirt to the hero."),
    ]


def test_completed_removal_then_transfer_applies_both_steps_to_same_item():
    actors, snapshot = fixtures()
    changed, accepted, errors = run(chain(), actors, snapshot)
    assert not errors and [row["action_index"] for row in accepted] == [0, 1]
    assert changed["NPC"]["inventory"] == []
    assert changed["NPC"]["visual_profile"]["worn"] == []
    assert changed[PLAYER]["inventory"] == [snapshot.items["SHIRT"]]
    assert changed[PLAYER]["visual_profile"]["worn"] == []


def test_invalid_terminal_action_rolls_back_whole_item_chain():
    actors, snapshot = fixtures()
    proposals = chain()
    proposals[1] = proposals[1].model_copy(update={"evidence": "This never happened."})
    changed, accepted, errors = run(
        proposals,
        actors,
        snapshot,
        narration="Anna removes her blue shirt. Anna hands the same blue shirt to the hero.",
    )
    assert errors and not accepted and changed == actors


def test_chain_in_reverse_narrative_order_is_not_reordered_by_host():
    actors, snapshot = fixtures()
    proposals = chain()
    changed, accepted, errors = run(
        proposals,
        actors,
        snapshot,
        narration="Anna hands the same blue shirt to the hero. Anna removes her blue shirt.",
    )
    assert errors and not accepted and changed == actors


def test_failed_wearing_after_handover_keeps_original_owner_and_outfit():
    actors, snapshot = fixtures()
    actors[PLAYER]["visual_profile"] = {"version": 999}
    proposals = [
        action(),
        action(
            source_owner=PLAYER,
            destination_owner=PLAYER,
            disposition="worn",
            evidence="The hero puts the shirt on.",
        ),
    ]
    changed, accepted, errors = run(proposals, actors, snapshot)
    assert errors and not accepted and changed == actors


def test_mechanics_already_applied_chain_is_not_repeated():
    actors, snapshot = fixtures()
    actors[PLAYER]["inventory"] = deepcopy(actors["NPC"]["inventory"])
    actors["NPC"]["inventory"] = []
    actors["NPC"]["resolved_inventory"] = []
    actors["NPC"]["visual_profile"]["worn"] = []
    snapshot.owners["SHIRT"] = PLAYER
    changed, accepted, errors = run(chain(), actors, snapshot)
    assert not errors and not accepted and changed == actors


def test_schema_rejected_chain_peer_cannot_leave_its_removal_applied():
    from backend.engine.narrated_items.independent_state import unpack
    from backend.engine.narrated_items.schema import SharedItemExtraction

    actors, snapshot = fixtures()
    valid, invalid = [entry.model_dump() for entry in chain()]
    invalid["disposition"] = "teleported"
    result, failures, denied, indices = unpack(
        SharedItemExtraction(actions=[valid, invalid]), actors
    )
    assert failures and "SHIRT" in denied
    changed, accepted, errors = run(result.actions, actors, snapshot)
    assert not errors and not accepted and changed == actors
    assert indices == ()


@pytest.mark.parametrize(
    "disposition,regions,valid",
    [
        ("worn", None, True),
        ("worn", [], True),
        ("worn", ["torso"], True),
        ("worn", ["torso", "torso"], False),
        ("held", None, True),
        ("held", [], False),
        ("carried", ["torso"], False),
    ],
)
def test_placement_wire_and_canonical_validation_agree(disposition, regions, valid):
    from jsonschema import Draft202012Validator

    raw = {**action().model_dump(), "disposition": disposition, "uncovered_regions": regions}
    assert Draft202012Validator(ItemAction.model_json_schema()).is_valid(raw) is valid
    if valid:
        assert ItemAction.model_validate(raw).uncovered_regions == regions
    else:
        with pytest.raises(ValidationError):
            ItemAction.model_validate(raw)


def test_failed_item_chain_preserves_unrelated_action_and_original_index():
    actors, snapshot = fixtures()
    remove, transfer = chain()
    unrelated = action(
        item_id=None,
        new_item={"kind": "ordinary", "name": "Notebook", "description": "A plain green notebook."},
        evidence="Anna gives a green notebook to the hero.",
    )
    transfer = transfer.model_copy(update={"evidence": "This transfer was never narrated."})
    changed, accepted, errors = run(
        [remove, unrelated, transfer],
        actors,
        snapshot,
        narration=remove.evidence + " " + unrelated.evidence,
    )
    assert errors and [entry["action_index"] for entry in accepted] == [1]
    assert changed["NPC"] == actors["NPC"]
    assert len(changed[PLAYER]["inventory"]) == 1
    assert changed[PLAYER]["inventory"][0]["name"] == "Notebook"


def test_interleaved_items_preserve_original_equipment_order():
    actors, snapshot = fixtures()
    scarf = {**deepcopy(snapshot.items["SHIRT"]), "id": "SCARF", "name": "Scarf"}
    actors["NPC"]["inventory"].append(scarf)
    actors["NPC"]["resolved_inventory"].append(scarf)
    snapshot.items["SCARF"] = scarf
    snapshot.owners["SCARF"] = "NPC"
    proposals = [
        action(
            disposition="worn", evidence="Anna gives the hero the shirt, which the hero puts on."
        ),
        action(
            item_id="SCARF",
            disposition="worn",
            evidence="Anna gives the hero the scarf, which the hero puts on.",
        ),
        action(
            source_owner=PLAYER,
            destination_owner="NPC",
            evidence="The hero removes the shirt and returns it to Anna.",
        ),
    ]
    changed, accepted, errors = run(proposals, actors, snapshot)
    assert not errors and [row["action_index"] for row in accepted] == [0, 1, 2]
    assert changed[PLAYER]["equipment"].get("Chest") is None
    assert changed[PLAYER]["visual_profile"]["worn"] == [
        {"item_id": "SCARF", "uncovered_regions": []}
    ]
