"""Current possession registration is not a transfer or a clothing-placement operation."""

from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from backend.engine.narrated_items import evidence, independent_state
from backend.engine.narrated_items.reference_schema import build
from backend.engine.narrated_items.schema import ItemAction, ItemExtraction, SharedItemExtraction
from backend.engine.narrated_items.source_catalog import Catalog
from backend.engine.visual_novel.continuity import PLAYER
from tests.test_narrated_items import action, fixtures, run

TEXT = "Anna is holding her plain paper map."


def observed(**changes):
    return {
        "item_id": None,
        "new_item": {"kind": "ordinary", "name": "Paper map", "description": "A plain paper map."},
        "source_owner": "NPC",
        "destination_owner": "NPC",
        "disposition": "held",
        "basis": "observed_possession",
        "evidence": TEXT,
        **changes,
    }


def test_current_held_discovery_registers_without_inventing_a_transfer():
    proposal = ItemExtraction.model_validate({"actions": [observed()]})
    actors, snapshot = fixtures()
    before = deepcopy(actors)
    changed, accepted, errors = run(proposal.actions, actors, snapshot, narration=TEXT)
    assert not errors and len(accepted) == 1
    registered = changed["NPC"]["inventory"][-1]
    assert registered["name"] == "Paper map"
    assert registered["id"] == accepted[0]["item"]["id"]
    assert accepted[0]["source_owner"] == accepted[0]["destination_owner"] == "NPC"
    assert changed["NPC"]["visual_profile"] == before["NPC"]["visual_profile"]
    assert changed[PLAYER] == before[PLAYER] and actors == before
    assert registered["item_origin"] == {
        "kind": "runtime",
        "session_id": "SESSION",
        "source_message_id": "TURN",
    }


def test_known_possession_observation_preserves_equipment_wear_order_and_metadata():
    actors, snapshot = fixtures()
    shirt = snapshot.items["SHIRT"]
    actors["NPC"]["equipment"] = {"Chest": deepcopy(shirt)}
    actors["NPC"]["visual_profile"]["worn"][0]["uncovered_regions"] = ["torso"]
    actors["NPC"]["inventory"].insert(0, {"id": "NOTE", "name": "Note"})
    actors["NPC"]["position"] = "beside the table"
    proposal = ItemAction.model_validate(observed(item_id="SHIRT", new_item=None))
    changed, accepted, errors = run([proposal], actors, snapshot)
    assert not errors and not accepted and changed == actors


def test_repeated_registered_possession_keeps_identity_without_reinsertion():
    actors, snapshot = fixtures()
    first, accepted, errors = run([ItemAction.model_validate(observed())], actors, snapshot)
    assert not errors
    item = accepted[0]["item"]
    snapshot.items[item["id"]] = item
    snapshot.owners[item["id"]] = "NPC"
    first["NPC"]["inventory"].append({"id": "NOTE", "name": "Note"})
    again, repeated, errors = run(
        [ItemAction.model_validate(observed(item_id=item["id"], new_item=None))], first, snapshot
    )
    assert not errors and not repeated and again == first


@pytest.mark.parametrize("owner", [PLAYER, "ABSENT", "__scene__"])
def test_observation_cannot_take_a_known_item_from_its_canonical_owner(owner):
    actors, snapshot = fixtures()
    snapshot.owners["SHIRT"] = owner
    proposal = ItemAction.model_validate(observed(item_id="SHIRT", new_item=None))
    changed, accepted, errors = run([proposal], actors, snapshot)
    assert errors and not accepted and changed == actors


def test_discovery_cannot_register_a_possession_for_an_absent_actor():
    actors, snapshot = fixtures()
    proposal = ItemAction.model_validate(
        observed(source_owner="ABSENT", destination_owner="ABSENT")
    )
    changed, accepted, errors = run([proposal], actors, snapshot)
    assert errors and not accepted and changed == actors


def test_discovery_cannot_recreate_an_unavailable_catalogued_item():
    actors, snapshot = fixtures()
    snapshot.catalog["MAP"] = {"id": "MAP", "name": "Paper map"}
    proposal = ItemAction.model_validate(observed())
    changed, accepted, errors = run([proposal], actors, snapshot)
    assert errors and not accepted and changed == actors


@pytest.mark.parametrize(
    "changes",
    [
        {"source_owner": PLAYER},
        {"source_owner": "__scene__"},
        {"source_owner": "__scene__", "destination_owner": "__scene__"},
        {"disposition": "worn"},
        {"uncovered_regions": []},
        {"attachment_slot": "anal"},
    ],
)
def test_observation_shape_cannot_authorize_transfer_or_placement(changes):
    with pytest.raises(ValidationError):
        ItemAction.model_validate(observed(**changes))


def test_observation_and_completed_steps_keep_same_item_chain_atomic():
    actors, snapshot = fixtures()
    proposals = [
        ItemAction.model_validate(observed(item_id="SHIRT", new_item=None)),
        action(destination_owner="NPC", evidence="Anna removes her blue shirt."),
        action(evidence="Anna hands that shirt to the hero."),
        ItemAction.model_validate(
            observed(
                item_id="SHIRT",
                new_item=None,
                source_owner=PLAYER,
                destination_owner=PLAYER,
                evidence="The hero now has the same shirt.",
            )
        ),
    ]
    narration = " ".join(proposal.evidence for proposal in proposals)
    changed, accepted, errors = run(proposals, actors, snapshot, narration=narration)
    assert not errors and [entry["action_index"] for entry in accepted] == [1, 2]
    assert changed["NPC"]["inventory"] == []
    assert changed[PLAYER]["inventory"] == [snapshot.items["SHIRT"]]
    proposals[-1] = proposals[-1].model_copy(update={"evidence": "A missing observation."})
    changed, accepted, errors = run(proposals, actors, snapshot, narration=narration)
    assert errors and not accepted and changed == actors


def test_invalid_observation_does_not_discard_independent_valid_item_or_scene_sections():
    actors, snapshot = fixtures()
    invalid = observed(item_id="SHIRT", new_item=None, source_owner=PLAYER)
    valid = observed(new_item={"kind": "ordinary", "name": "Note", "description": "A paper note."})
    supplied = SharedItemExtraction(
        actions=[invalid, valid],
        scene_updates=[{"operation": "record", "key": "lamp", "detail": "The lamp is lit."}],
    )
    extracted, failures, _, indices = independent_state.unpack(supplied, actors)
    assert failures and indices == (1,) and extracted.scene_updates == supplied.scene_updates
    changed, accepted, errors = run(extracted.actions, actors, snapshot)
    assert not errors and len(accepted) == 1
    assert changed["NPC"]["visual_profile"] == actors["NPC"]["visual_profile"]


@pytest.mark.parametrize("disposition", ["held", "carried"])
@pytest.mark.parametrize("new", [False, True])
def test_possession_wire_and_host_share_supported_branches(disposition, new):
    raw = observed(
        disposition=disposition, **({} if new else {"item_id": "SHIRT", "new_item": None})
    )
    payload = {"actions": [raw]}
    assert Draft202012Validator(ItemExtraction.model_json_schema()).is_valid(payload)
    parsed = ItemExtraction.model_validate(payload)
    assert ItemExtraction.model_validate_json(parsed.model_dump_json()) == parsed
    assert parsed.actions[0].basis == "observed_possession"


@pytest.mark.parametrize("new", [False, True])
@pytest.mark.parametrize(
    "changes",
    [
        {"disposition": "worn"},
        {"uncovered_regions": []},
        {"attachment_slot": "anal"},
        {"source_owner": "__scene__"},
    ],
)
def test_wire_excludes_possession_observation_from_placement_and_scene_acquisition(new, changes):
    raw = observed(**changes, **({} if new else {"item_id": "SHIRT", "new_item": None}))
    assert not Draft202012Validator(ItemExtraction.model_json_schema()).is_valid({"actions": [raw]})
    with pytest.raises(ValidationError):
        ItemExtraction.model_validate({"actions": [raw]})


@pytest.mark.parametrize("count", [6, 7])
def test_possession_registration_preserves_the_shared_action_limit(count):
    payload = {"actions": [observed()] * count}
    assert Draft202012Validator(ItemExtraction.model_json_schema()).is_valid(payload) is (
        count == 6
    )
    if count == 7:
        with pytest.raises(ValidationError):
            ItemExtraction.model_validate(payload)
        return
    assert len(ItemExtraction.model_validate(payload).actions) == count


def test_live_reference_contract_binds_observation_and_rejects_stale_source():
    catalog = Catalog(TEXT, "", scope="first")
    reference = next(iter(catalog.narration_passages))
    packet = {"actions": [observed(evidence=reference)]}
    assert Draft202012Validator(build(ItemExtraction, catalog)).is_valid(packet)
    bound = evidence.bind(packet, TEXT, catalog=catalog)
    assert bound.actions[0]["evidence"] == TEXT
    assert bound.actions[0]["evidence_span"] == {"start": 0, "end": len(TEXT)}
    stale = evidence.bind(packet, TEXT, catalog=Catalog(TEXT, "", scope="second"))
    extracted, failures, _, _ = independent_state.unpack(stale, fixtures()[0])
    assert failures and not extracted.actions


def test_observation_does_not_extend_the_clothing_recovery_contract():
    from backend.engine.clothing.recovery_schema import RecoveryAction

    with pytest.raises(ValidationError):
        RecoveryAction.model_validate(observed())


@pytest.mark.parametrize("length", [800, 801])
def test_possession_observation_retains_the_local_quote_limit(length):
    raw = observed(evidence="x" * length)
    assert Draft202012Validator(ItemExtraction.model_json_schema()).is_valid(
        {"actions": [raw]}
    ) is (length == 800)
    if length == 801:
        with pytest.raises(ValidationError):
            ItemExtraction.model_validate({"actions": [raw]})
        return
    assert ItemExtraction.model_validate({"actions": [raw]}).actions[0].evidence == raw["evidence"]


@pytest.mark.parametrize(
    "adult,detailed,accepted", [(True, True, True), (False, True, False), (True, False, False)]
)
def test_new_carried_clothing_keeps_existing_registration_policy(adult, detailed, accepted):
    actors, snapshot = fixtures()
    actors["NPC"]["age_years"] = 30 if adult else None
    proposal = ItemAction.model_validate(
        observed(
            new_item={
                "kind": "clothing",
                "name": "Cotton undershirt",
                "description": "A plain cotton undershirt.",
                "clothing": {"layer": 0, "coverage": ["torso"], "underwear": True},
                "wearable_slots": ["Chest"],
            }
        )
    )
    changed, results, errors = run([proposal], actors, snapshot, detailed=detailed)
    assert bool(results) is accepted and bool(errors) is not accepted
    assert changed["NPC"]["visual_profile"] == actors["NPC"]["visual_profile"]
