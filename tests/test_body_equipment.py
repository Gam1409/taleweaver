"""Body equipment extends canonical wear without duplicating inventory or clothing layers."""

from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from backend.engine.clothing.profiles import load_profile, validate_profile
from backend.engine.clothing.projection import visible_character
from backend.engine.narrated_items.schema import ItemAction, ItemExtraction
from backend.engine.visual_novel.continuity import PLAYER
from tests.test_narrated_items import action, fixtures, run


def setup_body(slots=None):
    actors, snapshot = fixtures()
    item = {"id": "SENSOR", "name": "Small sensor", "description": "A sealed medical sensor."}
    actors["NPC"]["inventory"].append(item)
    actors["NPC"]["resolved_inventory"].append(item)
    actors["NPC"]["visual_profile"]["body"] = {
        "form": "humanoid",
        "attachment_slots": slots,
    }
    snapshot.items[item["id"]], snapshot.owners[item["id"]] = item, "NPC"
    return actors, snapshot


def attach(**changes):
    return action(
        item_id="SENSOR",
        source_owner="NPC",
        destination_owner="NPC",
        disposition="worn",
        attachment_slot="anal",
        evidence="Anna positions the medical sensor in the named body slot.",
        **changes,
    )


def test_body_item_stays_one_owned_object_and_does_not_hide_clothing():
    actors, snapshot = setup_body(["anal"])
    before = deepcopy(actors)
    changed, accepted, errors = run([attach()], actors, snapshot)
    assert accepted and not errors
    assert len([item for item in changed["NPC"]["inventory"] if item["id"] == "SENSOR"]) == 1
    worn = changed["NPC"]["visual_profile"]["worn"]
    placement = next(row for row in worn if row["item_id"] == "SENSOR")
    assert placement["attachment_slot"] == "anal"
    assert placement["source"]["content_hash"] and placement["source"]["evidence"]
    projected = visible_character(
        changed["NPC"]["visual_profile"], changed["NPC"]["resolved_inventory"], detailed=True
    )
    assert [item["item_id"] for item in projected["clothing"]] == ["SHIRT"]
    assert actors == before


def test_completed_placement_can_establish_unassessed_region_but_not_override_known_absence():
    actors, snapshot = setup_body()
    changed, accepted, errors = run([attach()], actors, snapshot)
    assert accepted and not errors
    assert (
        next(row for row in changed["NPC"]["visual_profile"]["worn"] if row["item_id"] == "SENSOR")[
            "attachment_slot"
        ]
        == "anal"
    )
    actors, snapshot = setup_body([])
    changed, accepted, errors = run([attach()], actors, snapshot)
    assert errors and not accepted and changed == actors


def test_detach_and_transfer_remove_slot_binding_without_duplicating_or_dressing_recipient():
    actors, snapshot = setup_body(["anal"])
    actors, _, errors = run([attach()], actors, snapshot)
    assert not errors
    removal = action(
        item_id="SENSOR",
        source_owner="NPC",
        destination_owner=PLAYER,
        disposition="carried",
        evidence="Anna removes the sensor and hands it to the hero.",
    )
    changed, accepted, errors = run([removal], actors, snapshot)
    assert accepted and not errors
    assert all(row["item_id"] != "SENSOR" for row in changed["NPC"]["visual_profile"]["worn"])
    assert not changed[PLAYER]["visual_profile"]["worn"]
    assert sum(item["id"] == "SENSOR" for item in changed[PLAYER]["inventory"]) == 1


@pytest.mark.parametrize("basis", ["claim", "attempt", "hypothetical", "uncertain"])
def test_uncompleted_placement_does_not_establish_anatomy_or_change_wear(basis):
    actors, snapshot = setup_body()
    changed, accepted, errors = run([attach(basis=basis)], actors, snapshot)
    assert errors and not accepted and changed == actors


def test_attachment_contract_does_not_mix_clothing_displacement_or_carried_state():
    raw = attach().model_dump()
    for changes in [{"disposition": "carried"}, {"uncovered_regions": []}]:
        with pytest.raises(ValueError):
            ItemAction.model_validate({**raw, **changes})


def test_existing_profiles_keep_their_serialized_shape():
    raw = {
        "version": 1,
        "appearance": {"age_years": None, "hair": "", "eyes": "", "build": "", "features": ""},
        "worn": [{"item_id": "SHIRT", "uncovered_regions": []}],
    }
    profile = load_profile(raw)
    assert profile is not None and profile.model_dump() == raw
    actors, _ = setup_body(["anal"])
    invalid = deepcopy(actors["NPC"]["visual_profile"])
    invalid["worn"].append({"item_id": "SENSOR", "attachment_slot": "vaginal"})
    with pytest.raises(ValueError):
        validate_profile(invalid, actors["NPC"]["resolved_inventory"])


@pytest.mark.parametrize(
    "changes,valid",
    [
        ({}, True),
        ({"attachment_slot": None}, True),
        ({"attachment_slot": None, "uncovered_regions": ["torso"]}, True),
        ({"disposition": "held"}, False),
        ({"uncovered_regions": []}, False),
        ({"uncovered_regions": ["torso"]}, False),
    ],
)
def test_wire_and_host_agree_on_body_placement(changes, valid):
    payload = {"actions": [{**attach().model_dump(), **changes}]}
    assert Draft202012Validator(ItemExtraction.model_json_schema()).is_valid(payload) is valid
    if valid:
        assert ItemExtraction.model_validate(payload).actions
    else:
        with pytest.raises(ValueError):
            ItemExtraction.model_validate(payload)


@pytest.mark.parametrize("age", [None, 17])
def test_body_placement_does_not_infer_adulthood(age):
    actors, snapshot = setup_body()
    actors["NPC"]["age_years"] = age
    changed, accepted, errors = run([attach()], actors, snapshot)
    assert errors and not accepted and changed == actors


def test_clothing_cannot_be_relabelled_as_an_attachment_to_expose_lower_layers():
    actors, snapshot = setup_body()
    proposal = attach().model_copy(update={"item_id": "SHIRT"})
    changed, accepted, errors = run([proposal], actors, snapshot)
    assert errors and not accepted and changed == actors
    malformed = deepcopy(actors["NPC"]["visual_profile"])
    malformed["worn"][0]["attachment_slot"] = "anal"
    with pytest.raises(ValueError):
        validate_profile(malformed, actors["NPC"]["resolved_inventory"])
    visible = visible_character(malformed, actors["NPC"]["resolved_inventory"], detailed=True)
    assert visible["clothing"] == [] and visible["clothing_detail_limited"] is True


@pytest.mark.parametrize(
    "slots,age,kept",
    [(None, 30, True), (["anal"], 30, True), ([], 30, False), (["anal"], None, False)],
)
def test_manifest_normalization_keeps_valid_owned_body_items(slots, age, kept):
    from backend.engine.clothing.generation import normalize_manifest_clothing

    actors, _ = setup_body(slots)
    raw = deepcopy(actors["NPC"]["visual_profile"])
    raw["appearance"]["age_years"] = age
    raw["worn"].append({"item_id": "SENSOR", "attachment_slot": "anal"})
    manifest = {
        "npcs": [{"id": "NPC", "visual_profile": raw, "inventory": ["SHIRT", "SENSOR"]}],
        "objects": deepcopy(actors["NPC"]["inventory"]),
    }
    normalize_manifest_clothing(manifest, detailed=True)
    ids = [row["item_id"] for row in manifest["npcs"][0]["visual_profile"]["worn"]]
    assert ("SENSOR" in ids) is kept and "SHIRT" in ids
    assert len(manifest["objects"]) == 2
