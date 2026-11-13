"""Shared entity state retains script ordering, transaction and save boundaries."""

import asyncio
from copy import deepcopy

import pytest
from sqlalchemy import event, select

from backend.api.routes.adventures.sessions import copy_session
from backend.engine.gameplay.entity_state_updates import entity_state_updates, replace_entity_states
from backend.engine.rule_engine import GameEvent
from backend.engine.scripting.context import ScriptChangeset
from backend.engine.turn_replay.snapshot import capture, restore
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity, WorldExit, WorldScene
from tests.conftest import TestSessionLocal
from tests.test_turn_state_script_order import _manager, _pickup_event

pytestmark = pytest.mark.asyncio


async def test_failed_changeset_keeps_canonical_entity_state_unchanged(setup_test_db):
    async with TestSessionLocal() as db:
        manager = await _manager(db)
        before = deepcopy(manager.state.entity_states)
        changes = ScriptChangeset(
            entity_movements=[
                {"entity_id": "GUIDE", "to_scene_id": "OTHER"},
                {"entity_id": "TOKEN"},
            ],
            var_updates={"should_not_commit": True},
        )
        with pytest.raises(KeyError, match="to_scene_id"):
            await manager._apply_script_changeset(changes)
        assert manager.state.entity_states == before
        await db.commit()
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "session-1"))
        assert state.entity_states == before


async def test_successful_replacement_preserves_deletes_and_self_identity(setup_test_db):
    async with TestSessionLocal() as db:
        manager = await _manager(db)
        manager.state.entity_states = {
            "old": {"value": 1},
            "GUIDE": {"inventory": [{"id": "TOKEN"}]},
        }
        with entity_state_updates(manager.state) as canonical:
            replace_entity_states(manager.state, {"GUIDE": {"inventory": []}})
            assert manager.state.entity_states is canonical
            assert canonical == {"GUIDE": {"inventory": []}}
            replace_entity_states(manager.state, canonical)
            assert canonical == {"GUIDE": {"inventory": []}}
        await db.commit()
        await db.refresh(manager.state)
        assert manager.state.entity_states == canonical


async def test_script_commit_does_not_mutate_the_shared_orm_default(setup_test_db):
    async with TestSessionLocal() as db:
        manager = await _manager(db)
        default = SessionState.__table__.c.entity_states.default.arg
        before = deepcopy(default)
        fresh = SessionState(session_id=manager.game_id, current_scene_id="START")
        db.add(fresh)
        await db.flush()
        assert fresh.entity_states is default
        replace_entity_states(fresh, {**fresh.entity_states, "cross_session_probe": {"stamina": 0}})
        assert default == before
        later = SessionState(session_id=manager.game_id, current_scene_id="START")
        db.add(later)
        await db.flush()
        assert "cross_session_probe" not in later.entity_states


async def test_event_state_ownership_is_nested_session_local_and_cleared_on_cancel(setup_test_db):
    first = SessionState(entity_states={"GUIDE": {"hp": 10}})
    second = SessionState(entity_states=first.entity_states)
    with pytest.raises(asyncio.CancelledError), entity_state_updates(first) as outer:
        with entity_state_updates(second) as other, entity_state_updates(first) as nested:
            assert nested is outer
            assert other is not outer
            replace_entity_states(first, {"GUIDE": {"hp": 5}})
            assert second.entity_states["GUIDE"]["hp"] == 10
            replace_entity_states(second, {"TOKEN": {"is_hidden": True}})
            assert first.entity_states == {"GUIDE": {"hp": 5}}
        raise asyncio.CancelledError
    replace_entity_states(first, {"after_cancel": {"hp": 1}})
    assert first.entity_states is not outer
    assert outer == {"GUIDE": {"hp": 5}}


async def test_empty_event_does_not_write_entity_json(setup_test_db):
    async with TestSessionLocal() as db:
        manager = await _manager(db)
        before = deepcopy(manager.state.entity_states)
        statements = []

        def observe(_conn, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith("UPDATE SESSION_STATES"):
                statements.append(statement)

        engine = db.bind.sync_engine
        event.listen(engine, "before_cursor_execute", observe)
        try:
            await manager._apply_game_event(GameEvent())
            await db.commit()
        finally:
            event.remove(engine, "before_cursor_execute", observe)
        assert manager.state.entity_states == before
        assert not any("entity_states=" in statement for statement in statements)


async def test_nested_protagonist_and_pickup_callbacks_share_latest_state(setup_test_db):
    async with TestSessionLocal() as db:
        manager = await _manager(db)
        manager.avatar.stats = {"on_hp_change_script": "tw.vars.set('hp_callback', tw.player.hp)"}
        token = await db.scalar(select(WorldEntity).where(WorldEntity.id == "TOKEN"))
        token.metadata_json = {
            "on_pickup_script": "\n".join(
                [
                    "tw.player.modify_hp(-3)",
                    "tw.vars.set('pickup_seen', tw.objects.get('TOKEN').get_attribute('is_in_inventory'))",
                ]
            )
        }
        await manager._apply_game_event(_pickup_event())
        assert manager.avatar.hp == 97
        assert manager.state.entity_states["__script_vars__"] == {
            "hp_callback": 97,
            "pickup_seen": True,
        }
        assert manager.state.entity_states["TOKEN"]["is_in_inventory"] is True


async def test_scene_callback_and_later_event_updates_keep_exact_order(setup_test_db):
    async with TestSessionLocal() as db:
        manager = await _manager(db)
        db.add_all(
            [
                WorldScene(
                    id="END",
                    session_id=manager.game_id,
                    label="Gallery",
                    description="Gallery",
                    on_enter_scene_script="tw.npcs.get('GUIDE').hp = 8\ntw.vars.set('entered', True)",
                ),
                WorldExit(
                    session_id=manager.game_id,
                    from_scene_id="START",
                    to_scene_id="END",
                    label="Door",
                ),
            ]
        )
        guide = await db.scalar(select(WorldEntity).where(WorldEntity.id == "GUIDE"))
        guide.metadata_json = {
            "on_defeat_script": "tw.vars.set('defeat_hp', tw.npcs.get('GUIDE').hp)"
        }
        event_data = GameEvent.model_validate(
            {
                "new_scene_id": "END",
                "updated_entities": [{"entity_id": "GUIDE", "hp": 0, "is_defeated": True}],
            }
        )
        await manager._apply_game_event(event_data)
        assert manager.state.current_scene_id == "END"
        assert manager.state.entity_states["GUIDE"]["hp"] == 0
        assert manager.state.entity_states["__script_vars__"] == {"entered": True, "defeat_hp": 0}
        await db.commit()
        await db.refresh(manager.state)
        assert manager.state.entity_states["__script_vars__"]["defeat_hp"] == 0


async def test_partial_rejection_keeps_script_facts_and_only_accepted_mutations(setup_test_db):
    async with TestSessionLocal() as db:
        manager = await _manager(db)
        token = await db.scalar(select(WorldEntity).where(WorldEntity.id == "TOKEN"))
        token.metadata_json = {
            "on_pickup_script": "tw.vars.set('accepted', True)\ntw.story.reject_action('A scripted refusal.')"
        }
        proposal = _pickup_event(
            updated_entities=[
                {"entity_id": "UNKNOWN", "description": "Invalid"},
                {"entity_id": "GUIDE", "notes": "Accepted note"},
            ],
            remember_notes=["Unsafe derived fact"],
        )
        await manager._apply_game_event(proposal)
        assert "UNKNOWN" not in manager.state.entity_states
        assert manager.state.entity_states["GUIDE"]["notes"] == "Accepted note"
        assert manager.state.entity_states["__script_vars__"]["accepted"] is True
        assert not proposal.remember_notes


async def test_runtime_script_error_preserves_existing_prefix_changes_contract(setup_test_db):
    async with TestSessionLocal() as db:
        manager = await _manager(db)
        token = await db.scalar(select(WorldEntity).where(WorldEntity.id == "TOKEN"))
        token.metadata_json = {"on_pickup_script": "tw.vars.set('prefix', 1)\nunknown_function()"}
        messages = await manager._apply_game_event(_pickup_event())
        assert manager.state.entity_states["__script_vars__"]["prefix"] == 1
        assert any("Script Error" in str(message) for message in messages)
        await db.commit()
        await db.refresh(manager.state)
        assert manager.state.entity_states["__script_vars__"]["prefix"] == 1


async def test_spawn_and_script_commits_preserve_live_combat_references(setup_test_db):
    async with TestSessionLocal() as db:
        manager = await _manager(db)
        combat = {"active": True, "enemy": {"id": "GUIDE", "stamina": 20}}
        manager._set_combat_state(combat)
        states = manager.state.entity_states
        manager.combat._update_entity_state("TOKEN", is_in_inventory=True)
        assert manager.state.entity_states is not states
        assert manager._read_combat_state() is combat
        combat["enemy"]["stamina"] = 0
        await manager._apply_script_changeset(
            ScriptChangeset(var_updates={"combat_callback": True})
        )
        assert manager._read_combat_state() is combat
        assert manager._read_combat_state()["enemy"]["stamina"] == 0
        await manager._apply_game_event(_pickup_event())
        assert manager._read_combat_state() is combat
        await db.commit()
        await db.refresh(manager.state)
        assert manager._read_combat_state()["enemy"]["stamina"] == 0


async def test_script_state_survives_copy_and_replay_without_source_mutation(setup_test_db):
    async with TestSessionLocal() as db:
        manager = await _manager(db)
        before = await capture(db, manager.game_id)
        await manager._apply_game_event(_pickup_event())
        await db.commit()
        expected = deepcopy(manager.state.entity_states)
        copied = await copy_session(manager.game_id, db, manager.user)
        copied_id = copied["game_id"]
        copied_state = await db.scalar(
            select(SessionState).where(SessionState.session_id == copied_id)
        )
        assert copied_state.entity_states == expected
        await restore(db, manager.game_id, before)
        await db.commit()
        db.expunge_all()
        source = await db.scalar(
            select(SessionState).where(SessionState.session_id == manager.game_id)
        )
        copy = await db.scalar(select(SessionState).where(SessionState.session_id == copied_id))
        assert source.entity_states == before["state"]["entity_states"]
        assert copy.entity_states == expected
        assert copy.entity_states["__script_vars__"]["token_picked"] is True
