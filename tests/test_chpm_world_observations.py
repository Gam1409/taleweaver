"""Observer-only world facts never imply causation, omniscience or missing clothing."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.engine.chpm import appraisal_context, host_adapter, host_observations, motivation
from backend.engine.chpm.host_observation_contracts import HostFacts, Possession
from backend.engine.chpm.host_state import Source, before_messages, fingerprint, identifier
from backend.engine.chpm.schema import KernelState, Perception
from tests.test_chpm_host_state import mind, source


def test_capture_own_possessions_without_private_data_or_other_inventories():
    actor = SimpleNamespace(
        id="npc",
        inventory=[{"id": "key", "name": "Brass key", "secret": "private"}],
        visual_profile={"worn": [{"item_id": "key"}, {"item_id": "stale"}]},
        metadata_json={"thoughts": "never share"},
    )
    state = SimpleNamespace(
        current_scene_id="room", entity_states={"other": {"inventory": ["secret"]}}
    )
    facts = host_observations.capture(state, actor, {"npc": "Self", "visible": "Friend"})
    assert facts.visible_actor_ids == ("visible",)
    assert facts.owned_items == (Possession(id="key", name="Brass key"),)
    assert facts.worn_item_ids is None  # A stale worn reference makes placement unknown.
    assert "secret" not in facts.model_dump_json() and "thoughts" not in facts.model_dump_json()
    state.entity_states["npc"] = {"inventory": [], "visual_profile": {"worn": []}}
    empty = host_observations.capture(state, actor, {"npc": "Self"})
    assert empty.owned_items == empty.worn_item_ids == ()
    state.entity_states["npc"]["visual_profile"] = {"broken": True}
    assert host_observations.capture(state, actor, {}).worn_item_ids is None


def test_only_confirmed_differences_and_no_inferred_movement_when_observer_moves():
    a = HostFacts(
        scene_id="room",
        visible_actor_ids=("other",),
        owned_items=(Possession(id="key"),),
        worn_item_ids=("coat",),
    )
    b = HostFacts(scene_id="room", visible_actor_ids=("friend",), owned_items=(), worn_item_ids=())
    change = json.loads(host_observations.difference(a, b))
    assert change["cause"] == "unknown"
    assert change["own_items_lost"] == [{"id": "key", "name": ""}]
    assert change["own_worn_items_removed"] == ["coat"]
    assert change["visible_actors_removed"] == ["other"]
    moved = b.model_copy(update={"scene_id": "street"})
    changed = json.loads(host_observations.difference(a, moved))
    assert changed["own_scene_change"] == {"from": "room", "to": "street"}
    assert "visible_actors_added" not in changed and "visible_actors_removed" not in changed
    assert host_observations.difference(None, b) is None
    assert host_observations.difference(b, b) is None
    unknown = HostFacts(scene_id="room", visible_actor_ids=("other",))
    assert host_observations.difference(a, unknown) is None


def test_large_frame_is_valid_bounded_json_with_explicit_omissions():
    facts = HostFacts(
        scene_id="room",
        owned_items=tuple(Possession(id=f"item-{i}", name="Long label " * 14) for i in range(256)),
    )
    text = host_observations.frame(facts)
    assert len(text) <= 2000
    assert json.loads(text)["omitted"]["owned_items"] > 0
    assert len(facts.owned_items) == 256


def test_old_source_hashes_survive_and_new_frames_are_bound_to_full_facts():
    value = mind()
    old = source()
    raw = old.model_dump(exclude={"facts"})
    assert identifier(old, value.genesis) == fingerprint(
        {"scope": value.genesis.scope.model_dump(), "source": raw}
    )
    frame = source(kind="host_frame").model_copy(update={"facts": HostFacts(scene_id="room")})
    changed = frame.model_copy(update={"facts": HostFacts(scene_id="elsewhere")})
    assert identifier(frame, value.genesis) != identifier(changed, value.genesis)
    with pytest.raises(ValueError, match="host frame"):
        Source.model_validate({**raw, "facts": {"scene_id": "room"}})


async def test_prepare_records_world_delta_and_rollback_removes_its_sources(monkeypatch):
    monkeypatch.setattr(
        host_adapter.host_sources, "reconcile", AsyncMock(side_effect=lambda manager, value: value)
    )
    actor = SimpleNamespace(id="npc", name="NPC", inventory=[], metadata_json={})
    manager = SimpleNamespace(
        game_id="session", state=SimpleNamespace(current_scene_id="room", entity_states={})
    )
    turn = SimpleNamespace(
        initial=KernelState(minds={"npc": mind()}),
        minds={},
        present_names={"npc": "NPC", "other": "Other"},
        perceptions={"npc": Perception(actor_id="npc", quotes=[])},
    )
    observed = SimpleNamespace(
        session_id="session",
        scene_id="room",
        message_id="m1",
        revision_id=None,
        content_hash="hash",
        minute=1,
    )
    first = await host_adapter.prepare(manager, turn, actor, observed)
    assert [s.kind for s in first.sources.values()] == ["host_frame"]
    turn.initial.minds["npc"] = first
    manager.state.entity_states["npc"] = {"inventory": [{"id": "key", "name": "Brass key"}]}
    observed.message_id, observed.minute = "m2", 2
    second = await host_adapter.prepare(manager, turn, actor, observed)
    changes = [s for s in second.sources.values() if s.kind == "world_event"]
    assert len(changes) == 1 and "Brass key" in changes[0].text
    window = appraisal_context.build(second)
    assert window.payload["visible_evidence"][0]["kind"] == "witnessed"
    assert "other" in window.subjects
    catalogue = motivation.build(second, [], window)
    assert catalogue.sources["report-e1"].kind == "world_observation"
    assert catalogue.sources["report-e1"].status == "witnessed"
    current = host_adapter.context(second)["current_host_observations"][0]
    assert json.loads(current["text"])["observation"] == "current_host_state"
    assert before_messages(second, {"m2"}) == first
    assert turn.initial.minds["npc"].sources != second.sources
