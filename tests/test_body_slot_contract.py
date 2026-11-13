"""All declared placement groups share one persisted and transport vocabulary."""

from copy import deepcopy
from types import SimpleNamespace
from typing import get_args

import pytest
from jsonschema import Draft202012Validator

from backend.engine.clothing.body_schema import BodyLayout, BodySlot
from backend.engine.clothing.generation import normalize_manifest_clothing
from backend.engine.clothing.presentation import player_clothing
from backend.engine.clothing.recovery import evaluate
from backend.engine.clothing.recovery_schema import (
    RecoveryBodyAction,
    RecoveryEntry,
    RecoveryProposal,
)
from backend.engine.clothing.schema import VisualProfile
from backend.engine.narrated_items.schema import ItemAction, ItemExtraction
from tests.test_body_equipment import attach, setup_body
from tests.test_narrated_items import run

SLOTS = ("vaginal", "anal", "uterine", "penile")


def test_exactly_four_unique_regions_round_trip_without_a_schema_version_change():
    assert get_args(BodySlot) == SLOTS
    body = BodyLayout(attachment_slots=list(SLOTS))
    profile = VisualProfile(body=body)
    assert VisualProfile.model_validate(profile.model_dump()) == profile
    assert profile.version == 1
    with pytest.raises(ValueError):
        BodyLayout(attachment_slots=[*SLOTS, SLOTS[0]])


@pytest.mark.parametrize("slot", SLOTS)
def test_host_wire_and_recovery_agree_on_every_region(slot):
    raw = {**attach().model_dump(), "attachment_slot": slot}
    payload = {"actions": [raw]}
    assert Draft202012Validator(ItemExtraction.model_json_schema()).is_valid(payload)
    assert ItemExtraction.model_validate(payload).actions[0].attachment_slot == slot
    assert RecoveryBodyAction.model_validate(raw).attachment_slot == slot


@pytest.mark.parametrize("slot", SLOTS)
def test_each_region_preserves_ownership_and_explicit_unavailability(slot):
    proposal = ItemAction.model_validate({**attach().model_dump(), "attachment_slot": slot})
    actors, snapshot = setup_body([slot])
    changed, accepted, errors = run([proposal], actors, snapshot)
    assert accepted and not errors
    placement = changed["NPC"]["visual_profile"]["worn"][-1]
    assert placement["attachment_slot"] == slot and placement["source"]
    assert changed["NPC"]["inventory"] == actors["NPC"]["inventory"]
    actors["NPC"]["visual_profile"]["body"]["attachment_slots"] = []
    unchanged, accepted, errors = run([proposal], actors, snapshot)
    assert errors and not accepted and unchanged == actors


@pytest.mark.parametrize("slot", SLOTS)
@pytest.mark.parametrize("failure", ["age", "owner", "evidence"])
def test_every_region_keeps_existing_age_ownership_and_evidence_boundaries(slot, failure):
    actors, snapshot = setup_body([slot])
    raw = {**attach().model_dump(), "attachment_slot": slot}
    if failure == "age":
        actors["NPC"]["age_years"] = None
    elif failure == "owner":
        snapshot.owners["SENSOR"] = "__player__"
    else:
        raw["evidence"] = "An action absent from the source."
    proposal = ItemAction.model_validate(raw)
    changed, accepted, errors = run([proposal], actors, snapshot, narration=attach().evidence)
    assert errors and not accepted and changed == actors


@pytest.mark.parametrize("slot", SLOTS)
def test_reviewed_recovery_uses_the_same_group_and_source_contract(slot):
    actors, snapshot = setup_body([slot])
    raw = {**attach().model_dump(), "attachment_slot": slot}
    entry = RecoveryEntry(source_message_id="proof", action=raw)
    context = {
        "actor": actors["NPC"],
        "snapshot": snapshot,
        "messages": [{"id": "proof", "role": "assistant", "content": raw["evidence"]}],
    }
    changed, accepted, errors, _ = evaluate(
        context, RecoveryProposal(entries=[entry]), True, "session"
    )
    assert accepted and not errors
    worn = changed["NPC"]["visual_profile"]["worn"][-1]
    assert worn["attachment_slot"] == slot and worn["source"]["source_message_id"] == "proof"
    assert changed["NPC"]["inventory"] == actors["NPC"]["inventory"]


@pytest.mark.parametrize(
    "slot,key",
    list(zip(SLOTS, ("BodyVaginal", "BodyAnal", "BodyUterine", "BodyPenile"), strict=True)),
)
def test_owner_projection_and_initial_normalization_keep_distinct_region(slot, key):
    actors, _ = setup_body([slot])
    raw = deepcopy(actors["NPC"]["visual_profile"])
    raw["worn"].append({"item_id": "SENSOR", "attachment_slot": slot})
    manifest = {
        "npcs": [{"id": "NPC", "visual_profile": raw, "inventory": ["SHIRT", "SENSOR"]}],
        "objects": deepcopy(actors["NPC"]["inventory"]),
    }
    normalize_manifest_clothing(manifest, detailed=True)
    normalized = manifest["npcs"][0]["visual_profile"]
    assert normalized["worn"][-1]["attachment_slot"] == slot
    avatar = SimpleNamespace(**{**actors["NPC"], "visual_profile": normalized})
    data = player_clothing(avatar, {"clothing_settings": {"detailed": True}})
    assert data["attachments"][0]["slot"] == key
