"""Corrections pass canonical binding, scope and domain validation before staging."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.engine.narrated_items import evidence, repair_validation
from backend.engine.narrated_items.schema import SharedItemExtraction
from tests.test_condition_identity_echoes import initial
from tests.test_narrated_items import action, fixtures


def check(text, *, blocked=()):
    actors, snapshot = fixtures()
    source = evidence.Catalog(text, scope="preview-test")
    manager = SimpleNamespace(
        state=SimpleNamespace(entity_states=initial(), session_id="TEST", in_game_time=1)
    )
    validator = repair_validation.Check(
        manager,
        actors,
        snapshot,
        source,
        frozenset({"COAT", "BOTTLE", "SHIRT"}),
        False,
        True,
        "TURN",
        None,
        True,
        frozenset(blocked),
    )
    original = SharedItemExtraction(
        coverage={f"c{index}": ["conditions"] for index in range(len(source.narration_passages))},
        actions=[],
        condition_updates=[],
        scene_updates=[],
        final_frame_actions=[],
        movements=[],
    )
    return validator, original, list(source.narration_passages)


@pytest.mark.asyncio
async def test_valid_correction_is_checked_on_copies_without_early_commit():
    validator, original, refs = check("The coat is clean. The bottle is empty.")
    original.condition_updates = [
        {"operation": "clean", "condition_id": "DIRT", "evidence": refs[0]}
    ]
    candidate = original.model_copy(deep=True)
    candidate.condition_updates.append(
        {"operation": "change", "condition_id": "CONTENTS", "detail": "empty", "evidence": refs[1]}
    )
    before = deepcopy(validator.manager.state.entity_states)
    actors = deepcopy(validator.actors)
    assert await validator(original, original)
    assert await validator(candidate, original)
    assert validator.manager.state.entity_states == before and validator.actors == actors


@pytest.mark.asyncio
@pytest.mark.parametrize("part", ["contents", " contents "])
async def test_record_alias_cannot_extend_a_condition_chain_already_in_original(part):
    validator, original, refs = check("The bottle is empty. The bottle is full.")
    original.condition_updates = [
        {"operation": "change", "condition_id": "CONTENTS", "detail": "empty", "evidence": refs[0]}
    ]
    candidate = original.model_copy(deep=True)
    candidate.condition_updates.append(
        {
            "operation": "record",
            "target_id": "BOTTLE",
            "kind": "item_state",
            "part": part,
            "detail": "full",
            "evidence": refs[1],
        }
    )
    assert await validator(original, original)
    assert not await validator(candidate, original)


@pytest.mark.asyncio
async def test_casefolded_record_binding_cannot_reverse_original_condition():
    validator, original, refs = check("The mud stain is smaller. The mud stain is larger.")
    original.condition_updates = [
        {
            "operation": "change",
            "condition_id": "DIRT",
            "detail": "smaller mud stain",
            "evidence": refs[0],
        }
    ]
    candidate = original.model_copy(deep=True)
    candidate.condition_updates.append(
        {
            "operation": "record",
            "target_id": "COAT",
            "kind": "contamination",
            "part": " SURFACE ",
            "detail": "larger mud stain",
            "evidence": refs[1],
        }
    )
    assert await validator(original, original)
    assert not await validator(candidate, original)


@pytest.mark.asyncio
async def test_normalized_item_id_cannot_extend_an_original_item_chain():
    validator, original, refs = check(
        "Anna hands the shirt to the hero. The hero returns it to Anna."
    )
    original.coverage = {"c0": ["items"], "c1": ["items"]}
    original.actions = [action(item_id=" SHIRT ", evidence=refs[0]).model_dump()]
    original.actions[0]["item_id"] = " SHIRT "
    candidate = original.model_copy(deep=True)
    candidate.actions.append(
        action(source_owner="__player__", destination_owner="NPC", evidence=refs[1]).model_dump()
    )
    assert await validator(original, original)
    assert not await validator(candidate, original)


@pytest.mark.asyncio
@pytest.mark.parametrize("identity", ["UNKNOWN", "PRIVATE"])
async def test_foreign_or_unknown_condition_id_is_rejected_before_patch_acceptance(identity):
    validator, original, refs = check("The coat is clean. The bottle is empty.")
    candidate = original.model_copy(deep=True)
    candidate.condition_updates = [
        {"operation": "change", "condition_id": identity, "detail": "empty", "evidence": refs[1]}
    ]
    assert not await validator(candidate, original)


@pytest.mark.asyncio
async def test_rule_blocked_subject_and_unsupported_proof_are_not_repairable():
    validator, original, refs = check("The bottle is empty.", blocked={"BOTTLE"})
    candidate = original.model_copy(deep=True)
    candidate.condition_updates = [
        {"operation": "change", "condition_id": "CONTENTS", "detail": "empty", "evidence": refs[0]}
    ]
    assert not await validator(candidate, original)
    free, _, _ = check("The bottle is empty.")
    candidate.condition_updates[0]["evidence"] = "narration:foreign:p0"
    assert not await free(candidate, original)


@pytest.mark.asyncio
async def test_unchanged_property_update_cannot_clear_an_omission_warning():
    validator, original, refs = check("The bottle is still half full.")
    candidate = original.model_copy(deep=True)
    candidate.condition_updates = [
        {
            "operation": "change",
            "condition_id": "CONTENTS",
            "detail": "half full",
            "evidence": refs[0],
        }
    ]
    assert not await validator(candidate, original)


@pytest.mark.asyncio
async def test_historical_second_half_of_joined_proof_remains_blocked():
    validator, original, refs = check("The bottle is emptied. Yesterday the bottle was empty.")
    original.coverage["c1"] = ["historical"]
    candidate = original.model_copy(deep=True)
    candidate.condition_updates = [
        {
            "operation": "change",
            "condition_id": "CONTENTS",
            "detail": "empty",
            "evidence": refs[0] + "..p1",
        }
    ]
    assert not await validator(candidate, original)


@pytest.mark.asyncio
async def test_bad_added_item_does_not_reach_independence_filter_for_original_condition():
    validator, original, refs = check(
        "The mud stain is removed. An absent actor hands over the shirt."
    )
    original.condition_updates = [
        {"operation": "clean", "condition_id": "DIRT", "evidence": refs[0]}
    ]
    original.coverage["c1"] = ["items"]
    candidate = original.model_copy(deep=True)
    candidate.actions = [action(source_owner="ABSENT", evidence=refs[1]).model_dump()]
    assert await validator(original, original)
    assert not await validator(candidate, original)
