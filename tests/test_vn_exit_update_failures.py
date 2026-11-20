"""Derived map failures cannot invalidate an admitted canonical exit transition."""

from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.gameplay.turn_event_scenes import TurnEventScenes
from backend.engine.gameplay.world import AdventureLogic
from backend.engine.map_engine import MapEngine
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldExit
from tests.conftest import TestSessionLocal
from tests.test_vn_movement_recovery import install, proof, recovery_state
from tests.test_vn_movement_recovery_sources import UnlockRoles
from tests.test_vn_turn_integration import final_payload


def inject_owner_failure(monkeypatch, failure):
    original = TurnEventScenes._apply_exit_updates

    async def fail_row_query(execute, statement, *args, **kwargs):
        if any(row.get("entity") is WorldExit for row in statement.column_descriptions):
            raise SQLAlchemyError("Canonical row query failed")
        return await execute(statement, *args, **kwargs)

    async def fail_after_save(save, role, content):
        await save(role, content)
        raise SQLAlchemyError("Exit notice persistence failed")

    async def apply(self, event, messages):
        with monkeypatch.context() as scoped:
            if failure == "load":
                scoped.setattr(
                    AdventureLogic,
                    "get_or_create_map",
                    AsyncMock(side_effect=RuntimeError("Derived map unavailable")),
                )
            if failure == "register":
                scoped.setattr(
                    MapEngine,
                    "register_exit",
                    Mock(side_effect=ValueError("Derived map registration failed")),
                )
            if failure == "row_query":
                execute = self.db.execute
                scoped.setattr(
                    self.db,
                    "execute",
                    lambda statement, *args, **kwargs: fail_row_query(
                        execute, statement, *args, **kwargs
                    ),
                )
            if failure == "map_query":
                scoped.setattr(
                    AdventureLogic,
                    "get_or_create_map",
                    AsyncMock(side_effect=SQLAlchemyError("Derived map database query failed")),
                )
            if failure == "notice_flush":
                save = self.manager._save_chat_message
                scoped.setattr(
                    self.manager,
                    "_save_chat_message",
                    lambda role, content: fail_after_save(save, role, content),
                )
            await original(self, event, messages)

    monkeypatch.setattr(TurnEventScenes, "_apply_exit_updates", apply)


@pytest.mark.parametrize("mode", ["off", "live"])
@pytest.mark.parametrize("failure", ["load", "register"])
async def test_map_presentation_failure_preserves_accepted_unlock_and_hook_order(
    monkeypatch, mode, failure
):
    roles = UnlockRoles(proof=proof(), presence="present")
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _, state = await recovery_state(db, mode=mode, locked=True)
        edge = await db.scalar(select(WorldExit).where(WorldExit.session_id == state.session_id))
        edge.code_to_unlock = "1234"
        edge.on_unlock_success_script = "test-unlock-hook"
        edge.on_unlock_success_text = "The lock clicks open."
        state.exit_states = {edge.id: {"is_locked": True, "lock_description": "Preserve this."}}
        await db.commit()
        calls = []

        async def hook(manager, code, trigger, target):
            assert (
                code == "test-unlock-hook" and trigger == "on_unlock_success" and target == edge.id
            )
            assert (
                edge.is_locked is False and manager.state.exit_states[edge.id]["is_locked"] is False
            )
            calls.append(trigger)
            return ["Unlock script ran."]

        monkeypatch.setattr(GameTurnManager, "_execute_inline_script", hook)
        inject_owner_failure(monkeypatch, failure)
        manager = GameTurnManager(db, state.session_id, user)
        events = [event async for event in manager.process_turn("I enter 1234 on the door lock.")]
        assert final_payload(events)["status"] == "success", "".join(events)
        await db.refresh(state)
        await db.refresh(edge)
        assert state.entity_states["LINA"]["current_scene_id"] == "ANNEX"
        assert edge.is_locked is False
        assert state.exit_states[edge.id] == {
            "is_locked": False,
            "lock_description": "Preserve this.",
        }
        assert calls == ["on_unlock_success"]
        system = [
            row.content
            for row in await db.scalars(
                select(ChatMessage)
                .where(ChatMessage.role == "system")
                .order_by(ChatMessage.created_at, ChatMessage.id)
            )
        ]
        assert system.index("Exit unlocked: Door.") < system.index("The lock clicks open.")
        wire = "".join(events)
        assert (
            wire.index("Exit unlocked: Door.")
            < wire.index("Unlock script ran.")
            < wire.index("The lock clicks open.")
        )


@pytest.mark.parametrize("failure", ["row_query", "map_query", "notice_flush"])
async def test_critical_exit_database_failure_reaches_existing_turn_recovery(monkeypatch, failure):
    roles = UnlockRoles(proof=proof(), presence="present")
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _, state = await recovery_state(db, mode="off", locked=True)
        edge = await db.scalar(select(WorldExit).where(WorldExit.session_id == state.session_id))
        if failure == "notice_flush":
            # Exercise the save helper's existing ID-unhide commit before the later failure.
            edge.label = "Door ID: LINA"
        state.exit_states = {edge.id: {"is_locked": True}}
        await db.commit()
        inject_owner_failure(monkeypatch, failure)
        manager = GameTurnManager(db, state.session_id, user)
        events = [event async for event in manager.process_turn("I operate the door lock.")]
        assert any(event.startswith("event: error") for event in events), "".join(events)
        assert not any(event.startswith("event: final") for event in events)
        await db.refresh(state)
        edge = await db.scalar(select(WorldExit).where(WorldExit.session_id == state.session_id))
        assert state.entity_states.get("LINA", {}).get("current_scene_id", "START") == "START"
        assert edge.is_locked is True and state.exit_states[edge.id]["is_locked"] is True
        assert "ABSENT" not in state.entity_states
