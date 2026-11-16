"""Nested scene anchors obey existing source reconciliation, copy and rewind rules."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.engine.chpm import (
    agent,
    host_adapter,
    host_observations,
    host_sources,
    inference,
    lifecycle,
    semantic_recall,
)
from backend.engine.chpm.agent_contracts import Step
from backend.engine.chpm.host_state import before_messages
from backend.engine.chpm.schema import KernelState, Perception, Settings, Usage
from backend.engine.chpm.state import KEY, load
from backend.engine.session_exporter import SessionExporter
from backend.engine.session_importer import SessionImporter
from backend.engine.turn_replay.snapshot import capture, restore
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.test_chpm_host_turn import roles_for, run
from tests.test_chpm_observed_scene import ACTION, seed_frame


async def completed(db, monkeypatch):
    roles_for(monkeypatch)
    user, _, source = await seed_frame(db)
    manager, events = await run(db, user, "Can you answer?")
    assert any(chunk.startswith("event: final") for chunk in events), "".join(events)
    mind = load(manager.state).minds["LINA"]
    return manager, mind, source


@pytest.mark.parametrize("change", ["edit", "revision", "delete", "incomplete", "foreign"])
async def test_changed_scene_source_retracts_dependent_psychology(monkeypatch, change):
    async with TestSessionLocal() as db:
        manager, mind, scene = await completed(db, monkeypatch)
        rows = {row.id: row for row in await db.scalars(select(ChatMessage))}
        assert host_sources.from_messages(mind, rows) == mind
        if change == "edit":
            scene.content += " Revised."
        elif change == "revision":
            scene.revision_id = "different"
        elif change == "delete":
            rows.pop(scene.id)
        elif change == "incomplete":
            scene.npc_journal = {"status": "incomplete"}
        else:
            scene.session_id = "another-session"
        changed = host_sources.from_messages(mind, rows)
        assert changed == before_messages(mind, {scene.id})
        assert changed.snapshot.cursor < mind.snapshot.cursor
        assert changed.genesis == mind.genesis
        assert not host_observations.situation(changed)
        # This probe never writes the altered source or psychological projection.
        await db.rollback()


@pytest.mark.parametrize("include_scene", [True, False])
async def test_copy_remaps_the_scene_anchor_or_drops_its_dependent_suffix(
    monkeypatch, include_scene
):
    async with TestSessionLocal() as db:
        _, mind, scene = await completed(db, monkeypatch)
        mapping = {
            source.message_id: f"copy-{source.message_id}" for source in mind.sources.values()
        }
        if include_scene:
            mapping[scene.id] = "copied-scene-source"
        original = mind.model_dump_json()
        forked = lifecycle.fork(
            {KEY: KernelState(minds={"LINA": mind}).model_dump()}, mapping, "copy"
        )
        copied = KernelState.model_validate(forked[KEY]).minds["LINA"]
        assert copied.genesis.identity == mind.genesis.identity
        if include_scene:
            frame = host_observations.previous(copied)
            assert frame.last_observed_scene.source_message_id == "copied-scene-source"
            assert frame.last_observed_scene.actions[0].quote == ACTION
            assert scene.id not in json.dumps(host_observations.situation(copied))
        else:
            assert not host_observations.situation(copied)
        assert mind.model_dump_json() == original


async def test_large_inventory_does_not_displace_the_scene_and_omissions_are_explicit(monkeypatch):
    async with TestSessionLocal() as db:
        _, mind, _ = await completed(db, monkeypatch)
        facts = host_observations.previous(mind)
        value = facts.model_dump(mode="json")
        value["owned_items"] = [{"id": f"item-{i}", "name": "n" * 160} for i in range(256)]
        extended = type(facts).model_validate(value)
        before = deepcopy(extended.model_dump())
        projection = host_observations.frame(extended)
        assert len(projection) <= 2000
        data = json.loads(projection)
        assert data["last_observed_scene"]["actions"][0]["quote"] == ACTION
        assert data["omitted"]["owned_items"] > 0
        assert extended.model_dump() == before


async def test_lookup_and_memory_query_receive_the_verified_scene_without_extra_requests(
    monkeypatch,
):
    async with TestSessionLocal() as db:
        manager, mind, _ = await completed(db, monkeypatch)
        calls = []

        async def request(*args, **kwargs):
            calls.append(args[4])
            return Step(purpose="Current situation is sufficient", requests=[])

        monkeypatch.setattr(inference, "request", request)
        decision = load(manager.state).actors["LINA"]
        await agent.investigate(
            manager,
            Settings(mode="live", actor_ids=["LINA"], agent_steps=1),
            Usage(),
            mind,
            decision.observation,
            {"psychological_state": host_adapter.context(mind)},
        )
        assert len(calls) == 1
        assert ACTION in json.dumps(calls[0]["current_state"])
        turn = SimpleNamespace(
            perceptions={"LINA": Perception(actor_id="LINA", quotes=["Can you answer?"])},
            causal_threads={},
            scene_cues={"LINA": ACTION},
        )
        query = semantic_recall._query(turn, "LINA", "START")
        assert ACTION in query and "not automatically ongoing" in query and len(query) <= 3000


async def test_export_import_keeps_nested_scene_sources_reconcilable(monkeypatch):
    async with TestSessionLocal() as db:
        manager, mind, scene = await completed(db, monkeypatch)
        bundle = await SessionExporter.export_ads(db, manager.game_id)
        copied_id = await SessionImporter.import_ads(db, bundle, manager.user.id)
        assert copied_id
        state = await db.scalar(select(SessionState).where(SessionState.session_id == copied_id))
        copied = load(state).minds["LINA"]
        assert (
            await host_sources.reconcile(SimpleNamespace(db=db, game_id=copied_id), copied)
            == copied
        )
        moment = host_observations.previous(copied).last_observed_scene
        assert moment.source_message_id != scene.id
        assert moment.actions[0].quote == ACTION
        assert copied.genesis.identity == mind.genesis.identity


async def test_full_turn_restore_retains_the_same_observation_and_psychology(monkeypatch):
    async with TestSessionLocal() as db:
        manager, mind, _ = await completed(db, monkeypatch)
        saved = await capture(db, manager.game_id)
        manager.state.entity_states = {}
        await db.flush()
        await restore(db, manager.game_id, saved)
        await db.refresh(manager.state)
        restored = load(manager.state).minds["LINA"]
        assert restored == mind
        assert await host_sources.reconcile(manager, restored) == restored
