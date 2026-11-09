"""Observer-visible scene processes become citable events without inferred endings."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.engine.chpm import host_adapter, host_observations
from backend.engine.chpm.host_observation_contracts import HostFacts
from backend.engine.chpm.host_state import Mind, before_messages
from backend.engine.chpm.schema import KernelState, Perception
from backend.engine.scene_continuity.ledger import apply
from backend.engine.scene_continuity.schema import Ledger
from tests.test_chpm_host_state import mind
from tests.test_scene_continuity import KEY, apply_to, message, read, state, update


def actor():
    return SimpleNamespace(id="LINA", name="Lina", inventory=[], metadata_json={})


def facts(saved):
    return host_observations.capture(
        state(saved), actor(), {"LINA": "Lina"}, scene_targets={"LAB", "KETTLE", "WINDOW", "LINA"}
    )


def test_started_and_ended_processes_are_explicit_world_differences():
    before = facts({KEY: Ledger().model_dump()})
    saved, errors = apply_to()
    assert not errors
    running = facts(saved)
    first = json.loads(host_observations.difference(before, running))
    assert first["cause"] == "unknown"
    assert first["scene_facts_changed"][0]["status"] == "active"
    identifier = next(iter(read(saved).records))
    ended, errors = apply(
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
        minute=10,
        targets={"LAB", "KETTLE", "LINA", "__player__"},
        actor_targets={"LINA", "__player__"},
    )
    assert not errors
    last = json.loads(host_observations.difference(running, facts(ended)))
    assert last["scene_facts_changed"][0]["id"] == identifier
    assert last["scene_facts_changed"][0]["status"] == "ended"
    assert host_observations.difference(running, running) is None


def test_loss_of_access_is_unavailable_and_moving_rooms_does_not_end_processes():
    saved, _ = apply_to()
    before = facts(saved)
    missing = facts({KEY: Ledger().model_dump()})
    changed = json.loads(host_observations.difference(before, missing))
    assert changed["scene_facts_unavailable"] == [before.scene_facts[0].id]
    assert "ended" not in json.dumps(changed)
    moved = missing.model_copy(update={"scene_id": "street"})
    difference = json.loads(host_observations.difference(before, moved))
    assert "scene_facts_unavailable" not in difference
    assert "scene_facts_changed" not in difference
    assert difference["own_scene_change"] == {"from": "LAB", "to": "street"}
    assert host_observations.difference(before, HostFacts(scene_id="LAB")) is None


def test_private_processes_are_not_recorded_as_another_npcs_observations():
    saved, errors = apply_to(updates=[update(visibility="private", observers=["__player__"])])
    assert not errors
    before = facts({KEY: Ledger().model_dump()})
    assert facts(saved).scene_facts == ()
    assert host_observations.difference(before, facts(saved)) is None


async def test_scene_event_is_saved_with_current_input_and_retracted_on_rollback(monkeypatch):
    monkeypatch.setattr(
        host_adapter.host_sources, "reconcile", AsyncMock(side_effect=lambda manager, value: value)
    )
    original = mind()
    actor_value = SimpleNamespace(id="npc", name="NPC", inventory=[], metadata_json={})
    manager = SimpleNamespace(
        game_id="session",
        state=SimpleNamespace(current_scene_id="LAB", entity_states={KEY: Ledger().model_dump()}),
    )
    turn = SimpleNamespace(
        initial=KernelState(minds={"npc": original}),
        minds={},
        present_names={"npc": "NPC"},
        perceptions={"npc": Perception(actor_id="npc", quotes=[])},
    )
    observed = SimpleNamespace(
        session_id="session",
        scene_id="LAB",
        message_id="before",
        revision_id=None,
        content_hash="before-hash",
        minute=1,
    )
    # Use a room process so the ordinary manager scope already includes its subject.
    first = await host_adapter.prepare(manager, turn, actor_value, observed)
    turn.initial.minds["npc"] = first
    manager.state.entity_states, errors = apply_to(updates=[update(subject_id="LAB")])
    assert not errors
    observed.message_id, observed.minute, observed.content_hash = "after", 10, "after-hash"
    second = await host_adapter.prepare(manager, turn, actor_value, observed)
    events = [entry for entry in second.sources.values() if entry.kind == "world_event"]
    assert len(events) == 1 and "Kettle is boiling" in events[0].text
    assert events[0].message_id == "after"
    assert Mind.model_validate_json(second.model_dump_json()) == second
    assert before_messages(second, {"after"}) == first
