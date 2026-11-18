"""One established item never assesses unrelated clothing or reveals possible layers."""

from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.engine.chpm import host_observations
from backend.engine.clothing.body_schema import BODY_SLOT_KEYS
from backend.engine.clothing.changes import preview
from backend.engine.clothing.context import actor_records
from backend.engine.clothing.profiles import (
    load_profile,
    placement_profile,
    reconcile_profile,
    validate_profile,
)
from backend.engine.clothing.projection import (
    item_wear_state,
    known_worn_item_ids,
    visible_body_regions,
    visible_character,
)
from backend.engine.clothing.schema import MAX_UNASSESSED_WEAR_ITEMS, VisualProfile, WornItem
from backend.engine.gameplay.inventory_transfers import clear_dropped_references
from backend.engine.narrated_items.actor_items import receive, remove
from backend.engine.physical_conditions.ledger import apply as apply_conditions
from backend.engine.physical_conditions.visuals import project as visible_conditions
from tests.observable_state_support import world


def _item(identifier, layer=2, **metadata):
    return {
        "id": identifier,
        "name": identifier,
        "clothing": {"layer": layer, "coverage": ["torso", "arms"], **metadata},
    }


def _actor(items=None, profile=None):
    items = deepcopy(items if items is not None else [_item("OLD_COAT"), _item("LINING", 1)])
    return {
        "id": "NPC",
        "age_years": 30,
        "inventory": deepcopy(items),
        "resolved_inventory": items,
        "equipment": {},
        "visual_profile": deepcopy(profile),
    }


def test_missing_profile_wear_and_remove_resolve_only_the_named_item():
    actor = _actor()
    changed = preview(actor, "OLD_COAT", "wear", [], detailed=False)
    raw = changed["visual_profile"]
    assert raw["unassessed_wear_item_ids"] == ["LINING"]
    assert known_worn_item_ids(raw, changed["resolved_inventory"]) is None
    assert item_wear_state(raw, changed["resolved_inventory"], "OLD_COAT") == "worn"
    assert item_wear_state(raw, changed["resolved_inventory"], "LINING") == "unknown"
    carried = preview(changed, "OLD_COAT", "remove", [], detailed=False)
    assert (
        item_wear_state(carried["visual_profile"], carried["resolved_inventory"], "OLD_COAT")
        == "carried"
    )
    assert carried["visual_profile"]["unassessed_wear_item_ids"] == ["LINING"]
    assert actor["visual_profile"] is None


def test_first_carried_garment_does_not_assess_an_unstructured_outfit_or_expose_body_conditions():
    actor = _actor([])
    quote = "A bruise is visible on the wrist."
    states, _, errors = apply_conditions(
        {},
        [
            {
                "operation": "record",
                "target_id": "NPC",
                "kind": "injury",
                "part": "wrist",
                "detail": "A bruise.",
                "visibility": "public",
                "visual_detail": quote,
                "visual_region": "arms",
                "evidence": quote,
            }
        ],
        targets={"NPC"},
        narration=quote,
        message_id="reply",
        session_id="session",
        minute=1,
    )
    assert not errors
    state = SimpleNamespace(entity_states=states)
    assert not visible_conditions(state, {"NPC": actor}, detailed=True)
    receive(actor, _item("CARRIED"), "carried", False)
    assert (
        item_wear_state(actor["visual_profile"], actor["resolved_inventory"], "CARRIED")
        == "carried"
    )
    assert not visible_conditions(state, {"NPC": actor}, detailed=True)


def test_first_one_item_wear_does_not_complete_the_rest_of_an_unstructured_outfit():
    actor = _actor([_item("ONLY")])
    changed = preview(actor, "ONLY", "wear", [], detailed=False)
    raw, items = changed["visual_profile"], changed["resolved_inventory"]
    assert item_wear_state(raw, items, "ONLY") == "worn"
    assert known_worn_item_ids(raw, items) is None
    assert not visible_body_regions(raw, items)
    assert raw["wear_assessment_complete"] is False
    assert visible_character(raw, items)["clothing_detail_limited"]


def test_partial_profile_blocks_lower_layers_and_body_without_hiding_known_higher_layers():
    items = [_item("POSSIBLE_COAT", 2), _item("LOWER", 1), _item("OUTER", 3)]
    raw = {
        "worn": [{"item_id": "LOWER"}, {"item_id": "OUTER", "uncovered_regions": ["arms"]}],
        "unassessed_wear_item_ids": ["POSSIBLE_COAT"],
    }
    visible = visible_character(raw, items, detailed=True)
    assert [row["item_id"] for row in visible["clothing"]] == ["OUTER"]
    assert visible["clothing"][0]["visible_regions"] == ["torso"]
    assert visible["clothing_detail_limited"] is True
    assert not {"torso", "arms"} & visible_body_regions(raw, items)
    assert "POSSIBLE_COAT" not in str(visible) and "LOWER" not in str(visible)


@pytest.mark.parametrize(
    "unknown", [{"id": "UNKNOWN"}, {"id": "UNKNOWN", "clothing": {"bad": True}}]
)
def test_unassessed_invalid_or_id_only_coverage_blocks_all_visual_exposure(unknown):
    items = [unknown, _item("KNOWN", 3)]
    raw = {"worn": [{"item_id": "KNOWN"}], "unassessed_wear_item_ids": ["UNKNOWN"]}
    visible = visible_character(raw, items, detailed=True)
    assert visible["clothing"] == [] and visible["clothing_detail_limited"]
    assert not visible_body_regions(raw, items)


def test_owned_legacy_equipment_is_positive_but_stale_or_ambiguous_references_are_not():
    items = [_item("COAT")]
    assert item_wear_state(None, items, "COAT", equipment={"Chest": "COAT"}) == "worn"
    assert item_wear_state(None, items, "MISSING", equipment={"Chest": "MISSING"}) == "unknown"
    assert item_wear_state(None, items, "COAT", equipment={"Chest": {"id": []}}) == "unknown"
    assert item_wear_state({"worn": [{"item_id": "STALE"}]}, items, "COAT") == "unknown"
    ambiguous = [*items, {**items[0], "name": "A different item"}]
    assert item_wear_state(None, ambiguous, "COAT", equipment={"Chest": items[0]}) == "unknown"
    profile = placement_profile(None, ambiguous, "OTHER", equipment={"Chest": "COAT"})
    assert profile.unassessed_wear_item_ids == ["COAT"]


def test_receive_preserves_established_age_body_and_unrelated_wear_proof():
    host, rows = world()
    actor = actor_records(host, rows)["npc"]
    actor["visual_profile"]["body"] = {"form": "humanoid", "attachment_slots": []}
    actor["visual_profile"]["worn"][0]["source"] = {
        "source_message_id": "saved-reply",
        "content_hash": sha256(b"The coat is worn.").hexdigest(),
        "evidence": "The coat is worn.",
    }
    before = deepcopy(actor["visual_profile"])
    receive(actor, _item("NEW"), "carried", False)
    assert actor["visual_profile"] == load_profile(before).model_dump()
    assert item_wear_state(actor["visual_profile"], actor["resolved_inventory"], "NEW") == "carried"


@pytest.mark.parametrize(
    ("age", "detail", "allowed"),
    [(None, True, False), (17, True, False), (30, False, False), (30, True, True)],
)
def test_partial_bootstrap_never_infers_adulthood_or_bypasses_detail_policy(age, detail, allowed):
    actor = _actor()
    actor["age_years"] = age
    receive(actor, _item("BASE", 0, underwear=True), "carried", detail)
    assert actor["visual_profile"]["appearance"]["age_years"] == age
    if allowed:
        changed = preview(actor, "BASE", "wear", [], detailed=detail)
        assert (
            item_wear_state(changed["visual_profile"], changed["resolved_inventory"], "BASE")
            == "worn"
        )
    else:
        before = deepcopy(actor)
        with pytest.raises(ValueError, match="Detailed"):
            preview(actor, "BASE", "wear", [], detailed=detail)
        assert actor == before


def test_partial_knowledge_keeps_independent_attachment_and_held_item_transitions():
    slot = next(iter(BODY_SLOT_KEYS))
    actor = _actor(
        profile={
            "appearance": {"age_years": 30},
            "worn": [],
            "body": {"form": "humanoid", "attachment_slots": [slot]},
            "unassessed_wear_item_ids": ["OLD_COAT", "LINING"],
        }
    )
    item = {"id": "OBJECT", "name": "Small object"}
    receive(actor, item, "worn", True, WornItem(item_id="OBJECT", attachment_slot=slot))
    assert item_wear_state(actor["visual_profile"], actor["resolved_inventory"], "OBJECT") == "worn"
    remove(actor, "OBJECT")
    receive(actor, item, "held", True)
    assert (
        item_wear_state(actor["visual_profile"], actor["resolved_inventory"], "OBJECT") == "carried"
    )
    assert actor["visual_profile"]["unassessed_wear_item_ids"] == ["OLD_COAT", "LINING"]


def test_custody_loss_and_reconciliation_prune_only_lost_unknown_references():
    actor = _actor(profile={"worn": [], "unassessed_wear_item_ids": ["OLD_COAT", "LINING"]})
    remove(actor, "OLD_COAT")
    assert actor["visual_profile"]["unassessed_wear_item_ids"] == ["LINING"]
    raw = reconcile_profile(actor["visual_profile"], [])
    assert "unassessed_wear_item_ids" not in raw
    assert known_worn_item_ids(raw, []) == set()


def test_drop_owner_and_host_aggregate_do_not_reinterpret_unassessed_items_as_absent():
    actor = _actor(profile={"worn": [], "unassessed_wear_item_ids": ["OLD_COAT", "LINING"]})
    npc = SimpleNamespace(
        id="NPC",
        inventory=actor["inventory"],
        visual_profile=actor["visual_profile"],
        metadata_json={},
    )
    state = SimpleNamespace(current_scene_id="ROOM", entity_states={})
    assert host_observations.capture(state, npc, {}).worn_item_ids is None
    avatar = SimpleNamespace(equipment={}, visual_profile=deepcopy(actor["visual_profile"]))
    clear_dropped_references(SimpleNamespace(avatar=avatar), "OLD_COAT")
    assert avatar.visual_profile["unassessed_wear_item_ids"] == ["LINING"]
    assert actor["visual_profile"]["unassessed_wear_item_ids"] == ["OLD_COAT", "LINING"]


def test_legacy_complete_profiles_keep_their_serialized_shape_and_known_carry():
    legacy = VisualProfile(worn=[WornItem(item_id="COAT")]).model_dump()
    assert "unassessed_wear_item_ids" not in legacy and legacy["version"] == 1
    assert "wear_assessment_complete" not in legacy
    items = [_item("COAT"), _item("CARRIED")]
    assert VisualProfile.model_validate(legacy).model_dump() == legacy
    assert item_wear_state(legacy, items, "CARRIED") == "carried"
    assert known_worn_item_ids(legacy, items) == {"COAT"}


def test_unassessed_capacity_is_inclusive_and_overflow_rejects_before_inventory_overwrite():
    items = [_item(f"UNKNOWN_{index}") for index in range(MAX_UNASSESSED_WEAR_ITEMS)]
    actor = _actor(items)
    receive(actor, _item("NEW"), "carried", False)
    assert len(actor["visual_profile"]["unassessed_wear_item_ids"]) == MAX_UNASSESSED_WEAR_ITEMS
    assert load_profile(actor["visual_profile"]) is not None
    oversized = _actor([*items, _item("ONE_MORE")])
    before = deepcopy(oversized)
    with pytest.raises(ValidationError):
        receive(oversized, _item("NEW"), "carried", False)
    assert oversized == before
    complete = _actor([*items, _item("ONE_MORE")], {"worn": []})
    receive(complete, _item("NEW"), "carried", False)
    assert "unassessed_wear_item_ids" not in complete["visual_profile"]


def test_worn_limit_and_disjoint_owned_assessments_are_checked_after_local_mutation():
    items = [_item(f"WORN_{index}") for index in range(33)]
    profile = VisualProfile(worn=[WornItem(item_id=row["id"]) for row in items[:32]])
    profile.worn.append(WornItem(item_id=items[-1]["id"]))
    with pytest.raises(ValidationError):
        validate_profile(profile, items)
    with pytest.raises(ValidationError):
        VisualProfile(worn=[WornItem(item_id="COAT")], unassessed_wear_item_ids=["COAT"])
    with pytest.raises(ValueError, match="belong"):
        validate_profile({"unassessed_wear_item_ids": ["FOREIGN"]}, [])
