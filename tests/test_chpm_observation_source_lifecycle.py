"""State-source grounding keeps observer access, source lifetime and exact replay."""

import pytest

from backend.engine.chpm import (
    appraisal_context,
    experience,
    host_observations,
    lifecycle,
    motivation,
)
from backend.engine.chpm.agent_contracts import Lookup
from backend.engine.chpm.agent_tools import Tools
from backend.engine.chpm.host_state import Mind, before_messages, record_many
from backend.engine.chpm.observation_sources import LIMIT, current
from backend.engine.chpm.schema import KernelState
from backend.engine.chpm.state import KEY
from backend.engine.scene_continuity.ledger import apply
from backend.engine.scene_continuity.schema import Ledger
from tests.test_chpm_experience import proposed
from tests.test_chpm_kernel import observation
from tests.test_chpm_observation_triggers import assess, prepare
from tests.test_chpm_physical_observations import state_with_conditions
from tests.test_scene_continuity import KEY as SCENE_KEY
from tests.test_scene_continuity import apply_to, message, state, update


async def test_current_process_can_be_assessed_but_expired_and_other_room_cannot(monkeypatch):
    saved, errors = apply_to(updates=[update(subject_id="LAB", review_after_minutes=5)])
    assert not errors
    world = state(saved, minute=14)
    first = await prepare(monkeypatch, state=world)
    changed, _ = assess(first, "turn-1", marker="Kettle is boiling")
    assert changed.snapshot.experiences[0].level == "moderate"
    world.in_game_time = 15
    expired = await prepare(monkeypatch, state=world, previous=changed, message="turn-2")
    assert not current(expired, "turn-2")
    world.current_scene_id = "street"
    moved = await prepare(monkeypatch, state=world, previous=expired, message="turn-3")
    assert not current(moved, "turn-3")
    assert moved.snapshot.experiences == changed.snapshot.experiences


async def test_private_scene_knowledge_does_not_become_another_observers_trigger(monkeypatch):
    saved, errors = apply_to(
        updates=[update(subject_id="LAB", visibility="private", observers=["__player__"])]
    )
    assert not errors
    value = await prepare(monkeypatch, state=state(saved))
    assert not current(value, "turn-1")
    assert "Kettle is boiling" not in str(
        appraisal_context.build(value, current_message_id="turn-1").payload
    )


async def test_confirmed_process_ending_can_ground_a_changed_estimate(monkeypatch):
    saved, errors = apply_to(updates=[update(subject_id="LAB")])
    assert not errors
    world = state(saved)
    first, _ = assess(await prepare(monkeypatch, state=world), "turn-1", marker="Kettle is boiling")
    identifier = next(iter(Ledger.model_validate(saved[SCENE_KEY]).records))
    world.entity_states, errors = apply(
        saved,
        [
            {
                "operation": "end",
                "record_id": identifier,
                "visibility": "public",
                "evidence": "The kettle stops boiling.",
            }
        ],
        [],
        message=message("end", "The kettle stops boiling."),
        scene_id="LAB",
        scene_description="",
        session_id="session",
        minute=11,
        targets={"LAB", "npc", "__player__"},
        actor_targets={"npc", "__player__"},
    )
    assert not errors
    world.in_game_time = 11
    second = await prepare(monkeypatch, state=world, previous=first, message="turn-2")
    changed, _ = assess(second, "turn-2", marker="[ended]", level="absent")
    assert changed.snapshot.experiences[0].level == "absent"


async def test_unknown_empty_state_never_invents_an_observation_or_emotion(monkeypatch):
    from types import SimpleNamespace

    value = await prepare(
        monkeypatch, state=SimpleNamespace(current_scene_id="room", entity_states={})
    )
    assert not current(value, "turn-1")
    assert value.snapshot.experiences == ()


async def test_same_condition_in_another_room_keeps_its_existing_ground(monkeypatch):
    world = state_with_conditions()
    first, _ = assess(await prepare(monkeypatch, state=world), "turn-1")
    world.current_scene_id = "street"
    moved = await prepare(monkeypatch, state=world, previous=first, message="turn-2")
    with pytest.raises(ValueError, match="Repeated grounds"):
        assess(moved, "turn-2", level="high")


async def test_forty_quiet_turns_reuse_the_fact_and_do_not_heal_or_refresh_the_estimate(
    monkeypatch,
):
    world = state_with_conditions()
    value, _ = assess(await prepare(monkeypatch, state=world), "turn-1")
    original_identity = value.genesis
    for number in range(2, 42):
        world.in_game_time = number * 5
        value = await prepare(monkeypatch, state=world, previous=value, message=f"turn-{number}")
    assert len([row for row in value.sources.values() if row.kind == "host_observation"]) == 2
    assert value.genesis == original_identity
    assert value.snapshot.experiences[0].level == "moderate"
    assert experience.view(value)["states"][0]["status"] == "historical_current_unknown"
    with pytest.raises(ValueError, match="Repeated grounds"):
        assess(value, "turn-41", level="high")


async def test_full_inspection_cannot_reintroduce_compound_snapshot_roots(monkeypatch):
    value = await prepare(monkeypatch)
    tools = Tools(value, observation(message_id="turn-1"), {})
    result = tools.execute(Lookup(tool="inspect_self"))
    window = appraisal_context.build(value, current_message_id="turn-1", pinned=tools.pins)
    proposal = proposed(
        about_id=None, citations=[{"source_id": result["source_id"], "quote": "OWN_PRIVATE_WOUND"}]
    )
    with pytest.raises(ValueError, match="specific host observation"):
        experience.accept(
            value, [proposal], window, motivation.build(value, [], window), message_id="turn-1"
        )


async def test_copy_rebinds_state_and_experience_then_rewind_removes_both(monkeypatch):
    first = await prepare(monkeypatch)
    changed, _ = assess(first, "turn-1")
    forked = lifecycle.fork(
        {KEY: KernelState(minds={"npc": changed}).model_dump()}, {"turn-1": "copy-1"}, "copied"
    )
    copied = KernelState.model_validate(forked[KEY]).minds["npc"]
    assert current(copied, "copy-1")
    assert copied.genesis.identity == changed.genesis.identity
    assert copied.snapshot.experiences[0].level == "moderate"
    with pytest.raises(ValueError, match="Repeated grounds"):
        assess(copied, "copy-1", level="high")
    assert not before_messages(copied, {"copy-1"}).sources
    assert not before_messages(copied, {"copy-1"}).snapshot.experiences
    assert Mind.model_validate_json(changed.model_dump_json()) == changed


async def test_saved_observation_cannot_be_detached_from_its_canonical_frame(monkeypatch):
    value = await prepare(monkeypatch)
    full_frame = next(row for row in value.sources.values() if row.kind == "host_frame")
    specific = next(row for row in value.sources.values() if row.kind == "host_observation")
    from tests.test_chpm_host_state import mind

    empty = mind()
    with pytest.raises(ValueError, match="earlier full state frame"):
        record_many(empty, [specific], minute=0)
    forged = specific.model_copy(update={"content_hash": "different"})
    with pytest.raises(ValueError, match="source anchor"):
        record_many(empty, [full_frame, forged], minute=0)


async def test_projection_adds_only_a_bounded_batch_and_preserves_full_state(monkeypatch):
    saved, errors = apply_to(
        updates=[update(key=f"kettle-{number}", subject_id="LAB") for number in range(LIMIT + 3)]
    )
    assert not errors
    world = state(saved)
    first = await prepare(monkeypatch, state=world)
    assert len(current(first, "turn-1")) == LIMIT
    assert (
        appraisal_context.build(first, current_message_id="turn-1").payload[
            "current_observations_omitted"
        ]
        == 3
    )
    assert len(host_observations.previous(first).scene_facts) == LIMIT + 3
    second = await prepare(monkeypatch, state=world, previous=first, message="turn-2")
    assert len(current(second, "turn-2")) <= LIMIT
    assert (
        len([row for row in second.sources.values() if row.kind == "host_observation"]) == LIMIT + 3
    )
    assert Ledger.model_validate(world.entity_states[SCENE_KEY]).records
