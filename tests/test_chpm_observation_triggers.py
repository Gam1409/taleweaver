"""Current observations can ground experience without refreshing unchanged facts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.engine.chpm import appraisal_context, experience, host_adapter, motivation
from backend.engine.chpm.host_state import Mind
from backend.engine.chpm.schema import KernelState, Perception
from tests.test_chpm_experience import proposed
from tests.test_chpm_host_state import mind
from tests.test_chpm_kernel import observation
from tests.test_chpm_physical_observations import actor, change, state_with_conditions


async def prepare(monkeypatch, *, previous=None, state=None, message="turn-1"):
    monkeypatch.setattr(
        host_adapter.host_sources, "reconcile", AsyncMock(side_effect=lambda manager, value: value)
    )
    state = state or state_with_conditions()
    manager = SimpleNamespace(game_id="session", state=state)
    turn = SimpleNamespace(
        initial=KernelState(minds={"npc": previous or mind()}),
        minds={},
        present_names={"npc": "Rin", "other": "Other"},
        perceptions={"npc": Perception(actor_id="npc", quotes=[])},
    )
    observed = observation(message_id=message).model_copy(
        update={
            "scene_id": state.current_scene_id,
            "minute": getattr(state, "in_game_time", 0),
        }
    )
    return await host_adapter.prepare(manager, turn, actor(), observed)


def assess(value, message, *, level="moderate", marker="OWN_PRIVATE_WOUND"):
    window = appraisal_context.build(value, current_message_id=message)
    alias, (_, source, _) = next(
        (alias, entry)
        for alias, entry in window.sources.items()
        if entry[1].kind == "host_observation" and marker in entry[1].text
    )
    body = proposed(about_id=None, level=level, citations=[{"source_id": alias, "quote": marker}])
    return experience.accept(
        value, [body], window, motivation.build(value, [], window), message_id=message
    )[0], source


async def test_first_body_observation_can_ground_experience_without_player_speech(monkeypatch):
    value = await prepare(monkeypatch)
    changed, _ = assess(value, "turn-1")
    assert changed.snapshot.experiences[0].level == "moderate"
    assert changed.genesis == value.genesis
    assert "FOREIGN_BODY_SECRET" not in str(appraisal_context.build(value).payload)
    assert Mind.model_validate_json(changed.model_dump_json()) == changed
    visible = appraisal_context.build(value, current_message_id="turn-1").payload[
        "visible_evidence"
    ]
    wound = next(row for row in visible if "OWN_PRIVATE_WOUND" in row["text"])
    coat = next(row for row in visible if "OWN_COAT_DIRT" in row["text"])
    assert wound["target_id"] == "npc" and wound["part"] == "neck"
    assert coat["target_id"] == "coat"
    assert wound["channel"] == coat["channel"] == "host_observation"


async def test_unrelated_inventory_change_does_not_make_the_same_wound_new_ground(monkeypatch):
    state = state_with_conditions()
    first, source = assess(await prepare(monkeypatch, state=state), "turn-1")
    state.entity_states = {
        **state.entity_states,
        "npc": {
            "inventory": [{"id": "coat", "name": "Coat"}, {"id": "key", "name": "Key"}],
        },
    }
    second = await prepare(monkeypatch, state=state, previous=first, message="turn-2")
    assert any(row.kind == "world_event" and "key" in row.text for row in second.sources.values())
    with pytest.raises(ValueError, match="Repeated grounds"):
        assess(second, "turn-2", level="high")
    assert second.snapshot.experiences == first.snapshot.experiences
    assert list(second.sources.values()).count(source) == 1
    window = appraisal_context.build(second, current_message_id="turn-2")
    repeated = next(
        row for row in window.payload["visible_evidence"] if "OWN_PRIVATE_WOUND" in row["text"]
    )
    assert repeated["already_supports_states"] == ["x1"]


async def test_unchanged_observation_can_receive_its_first_assessment_later(monkeypatch):
    first = await prepare(monkeypatch)
    second = await prepare(monkeypatch, previous=first, message="turn-2")
    changed, source = assess(second, "turn-2")
    assert source.message_id == "turn-1"
    assert changed.snapshot.experiences[0].level == "moderate"
    assert len([row for row in second.sources.values() if row.kind == "host_observation"]) == 2


async def test_explicit_healing_supplies_new_ground_and_missing_state_does_not(monkeypatch):
    state = state_with_conditions()
    first, _ = assess(await prepare(monkeypatch, state=state), "turn-1")
    condition = next(
        row
        for row in first.sources.values()
        if row.kind == "host_observation" and "OWN_PRIVATE_WOUND" in row.text
    )
    identifier = condition.facts.physical_conditions[0].id
    change(state, identifier, "heal", "The neck wound is completely healed.")
    second = await prepare(monkeypatch, state=state, previous=first, message="turn-2")
    changed, _ = assess(second, "turn-2", level="absent", marker="[resolved]")
    assert changed.snapshot.experiences[0].level == "absent"
    state.entity_states = {}
    unknown = await prepare(monkeypatch, state=state, previous=changed, message="turn-3")
    window = appraisal_context.build(unknown, current_message_id="turn-3")
    assert not any(row.kind == "host_observation" for _, row, _ in window.sources.values())
