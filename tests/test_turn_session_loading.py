"""A reused turn manager must reload expired relationships before reading session flags."""

import pytest
from sqlalchemy import inspect

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.models.game_session import GameSession
from tests.conftest import TestSessionLocal
from tests.test_game_loop import _seed_game_context


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "epilogue_sent", "pending", "locked"),
    [
        ("active", False, False, False),
        ("completed", False, True, False),
        ("game_over", False, True, False),
        ("game_over", True, False, True),
    ],
)
async def test_reused_manager_reloads_session_after_state_refresh(
    setup_test_db, status, epilogue_sent, pending, locked
):
    async with TestSessionLocal() as db:
        user, adventure, avatar, state = await _seed_game_context(db)
        db.add(
            GameSession(
                id=state.session_id,
                template_id=adventure.id,
                avatar_id=avatar.id,
                user_id=user.id,
                adventure_title=adventure.title,
                status="active",
            )
        )
        await db.commit()
        manager = GameTurnManager(db, state.session_id, user)
        assert await manager.initialize()
        state.session.status = status
        state.exit_states = {"__terminal_epilogue__": {"game_over_sent": epilogue_sent}}
        await db.commit()
        await db.refresh(state)
        assert "session" in inspect(state).unloaded

        assert await manager.initialize()

        assert manager._is_terminal_epilogue_pending() is pending
        assert manager._is_input_locked() is locked
        assert "session" not in inspect(state).unloaded
