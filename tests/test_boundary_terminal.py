"""Status-effect death follows the existing terminal finalization before the next turn."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.gameplay.turn_pass_flow import advance_completed_boundary, turn_anchor
from backend.engine.rule_engine import GameEvent
from backend.engine.scripting.runner import ScriptRunner
from tests.conftest import TestSessionLocal
from tests.test_terminal_progress import SID, context, terminal_world

__all__ = ["terminal_world"]


SCRIPTS = [
    {"id": "END", "trigger": "on_turn_end", "code": "tw.vars.set('turn_ended', True)"},
    {"id": "START", "trigger": "on_turn_start", "code": "tw.vars.set('next_turn_started', True)"},
]


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["scene", "sequence"])
async def test_poison_boundary_finalizes_once_and_does_not_start_next_turn(
    terminal_world, boundary
):
    async with TestSessionLocal() as db:
        _, state, avatar, user = await context(db)
        avatar.hp, avatar.status_effects = 1, ["Poisoned"]
        manager = GameTurnManager(db, SID, user)
        assert await manager.initialize()
        manager._turn_anchor = turn_anchor(state)
        if boundary == "scene":
            state.current_scene_id = "NEXT"
        else:
            state.active_sequence_id = "NEXT_SEQUENCE"
        event = GameEvent()
        chunks = [
            chunk
            async for chunk in advance_completed_boundary(manager, ScriptRunner(SCRIPTS), event)
        ]
        assert event.game_over is True
        assert event.status_note == "Hero has fallen! Game Over."
        assert avatar.hp == 0 and state.session.status == "game_over"
        assert state.entity_states["__script_vars__"]["turn_ended"] is True
        assert "next_turn_started" not in state.entity_states["__script_vars__"]
        assert sum("[Poisoned]" in chunk for chunk in chunks) == 1
        assert [
            chunk
            async for chunk in advance_completed_boundary(manager, ScriptRunner(SCRIPTS), event)
        ] == []
        await db.commit()
    async with TestSessionLocal() as db:
        session, state, avatar, user = await context(db)
        assert avatar.hp == 0 and session.status == "game_over" and state.in_game_time == 7
        assert len(user.game_log) == 1 and user.game_log[0]["status"] == "game_over"
        assert not user.earned_awards


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,effects,hp,expected",
    [("vn", ["Poisoned"], 1, 1), ("rpg", ["Poisoned"], 100, 95), ("rpg", [], 1, 1)],
)
async def test_nonlethal_or_vn_boundary_keeps_existing_turn_script_order(
    terminal_world, mode, effects, hp, expected
):
    async with TestSessionLocal() as db:
        _, state, avatar, user = await context(db)
        manager = GameTurnManager(db, SID, user)
        assert await manager.initialize()
        manager.adventure.rule_enforcement_mode = mode
        avatar.hp, avatar.status_effects = hp, effects
        manager._turn_anchor = turn_anchor(state)
        state.current_scene_id = "NEXT"
        event = GameEvent()
        _ = [
            chunk
            async for chunk in advance_completed_boundary(manager, ScriptRunner(SCRIPTS), event)
        ]
        assert (
            avatar.hp == expected and state.session.status == "active" and event.game_over is False
        )
        assert state.entity_states["__script_vars__"] == {
            "turn_ended": True,
            "next_turn_started": True,
        }


@pytest.mark.asyncio
async def test_boundary_cancellation_does_not_finalize_a_live_session(terminal_world):
    async with TestSessionLocal() as db:
        _, state, _, user = await context(db)
        manager = GameTurnManager(db, SID, user)
        assert await manager.initialize()
        manager._turn_anchor = turn_anchor(state)
        state.current_scene_id = "NEXT"
        manager._build_script_context = AsyncMock(side_effect=asyncio.CancelledError())
        with pytest.raises(asyncio.CancelledError):
            _ = [
                chunk
                async for chunk in advance_completed_boundary(
                    manager, ScriptRunner(SCRIPTS), GameEvent()
                )
            ]
        assert state.session.status == "active" and state.in_game_time == 0
