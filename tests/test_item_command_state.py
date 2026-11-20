"""Actor commands update owned item facts with honest provenance and stable identities."""

from copy import deepcopy
from hashlib import sha256

import pytest

from backend.engine.physical_conditions.command_source import CommandProof
from backend.engine.physical_conditions.item_commands import apply_command
from backend.engine.physical_conditions.ledger import read, remap
from backend.engine.physical_conditions.schema import Source


def proof(identifier="operation-1"):
    return CommandProof(id=identifier, actor_id="NPC", operation="change_item_state")


def change(states, identifier="operation-1", **changes):
    return apply_command(
        states,
        item_id="COAT",
        dimension="damage",
        detail="The cuff is torn.",
        owned_item_ids={"COAT"},
        proof=proof(identifier),
        message_id="input",
        request_hash=sha256(identifier.encode()).hexdigest(),
        session_id="session",
        minute=5,
        **changes,
    )


def test_command_property_is_not_mislabeled_as_narration_player_or_manual_input():
    original = {}
    changed, condition_id = change(original)
    assert original == {}
    row = read(changed).conditions[condition_id]
    assert row.target_id == "COAT" and row.kind == "item_state" and row.part == "damage"
    assert row.latest.kind == "command" and row.latest.command == proof()
    assert row.latest.message_id == "input" and row.detail == "The cuff is torn."


def test_subsequent_command_reuses_condition_id_and_recent_replay_is_a_noop():
    first, condition_id = change({})
    second, updated = apply_command(
        first,
        item_id="COAT",
        dimension="damage",
        detail="The cuff is repaired.",
        owned_item_ids={"COAT"},
        proof=proof("operation-2"),
        message_id="input",
        request_hash=sha256(b"operation-2").hexdigest(),
        session_id="session",
        minute=5,
    )
    assert condition_id == updated and len(read(second).conditions) == 1
    unchanged, _ = apply_command(
        second,
        item_id="COAT",
        dimension="damage",
        detail="The cuff is repaired.",
        owned_item_ids={"COAT"},
        proof=proof("operation-2"),
        message_id="input",
        request_hash=sha256(b"operation-2").hexdigest(),
        session_id="session",
        minute=5,
    )
    assert unchanged == second


def test_unowned_target_is_rejected_before_replacing_any_previous_fact():
    states, _ = change({})
    previous = deepcopy(states)
    with pytest.raises(ValueError, match="own"):
        apply_command(
            states,
            item_id="OTHER_COAT",
            dimension="damage",
            detail="Changed.",
            owned_item_ids={"COAT"},
            proof=proof("foreign"),
            message_id="input",
            request_hash=sha256(b"foreign").hexdigest(),
            session_id="session",
            minute=5,
        )
    assert states == previous


def test_command_sources_remap_with_the_real_input_and_missing_sources_stay_historical():
    states, identifier = change({})
    copied = remap(states, {"input": "copied-input"})
    assert read(copied).conditions[identifier].latest.message_id == "copied-input"
    assert read(copied).conditions[identifier].latest.kind == "command"
    missing = remap(states, {})
    assert read(missing).conditions[identifier].latest.kind == "unavailable"
    assert read(missing).conditions[identifier].detail == "The cuff is torn."


def test_legacy_source_serialization_has_no_new_null_proof_field():
    source = Source(kind="manual", quote="A recorded fact.")
    assert "command" not in source.model_dump()
    assert Source.model_validate(source.model_dump()) == source


def test_reused_identity_with_different_property_data_is_rejected_even_with_an_old_hash():
    states, _ = change({})
    before = deepcopy(states)
    with pytest.raises(ValueError, match="different request"):
        apply_command(
            states,
            item_id="COAT",
            dimension="damage",
            detail="Different state.",
            owned_item_ids={"COAT"},
            proof=proof(),
            message_id="input",
            request_hash=sha256(b"operation-1").hexdigest(),
            session_id="session",
            minute=5,
        )
    assert states == before


@pytest.mark.parametrize(
    "dimension",
    [
        "owner_id",
        "worn_by",
        "uncovered_regions",
        "current_scene_id",
        "visual_profile",
        "is_hidden",
        "posture",
        "emotion",
    ],
)
def test_descriptive_properties_cannot_create_a_parallel_owner_wardrobe_or_character_state(
    dimension,
):
    with pytest.raises(ValueError, match="identity|mechanical|owner"):
        apply_command(
            {},
            item_id="COAT",
            dimension=dimension,
            detail="A replacement state.",
            owned_item_ids={"COAT"},
            proof=proof(),
            message_id="input",
            request_hash=sha256(b"request").hexdigest(),
            session_id="session",
            minute=0,
        )
