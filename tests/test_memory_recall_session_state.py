"""RAG source refresh must keep the turn's session relationship usable without lazy IO."""

from types import SimpleNamespace

import pytest
from sqlalchemy import event, inspect, select, update
from sqlalchemy.orm import selectinload

from backend.api.routes.adventures.turn_helpers import TurnSessionStateHelper
from backend.engine.memory_rag.documents import collect_documents
from backend.engine.memory_rag.retrieval import prepare_recall
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]


@pytest.mark.parametrize("through_recall", [False, True])
@pytest.mark.parametrize(
    "status,sent,pending,locked",
    [
        ("active", False, False, False),
        ("completed", False, True, False),
        ("game_over", False, True, False),
        ("game_over", True, False, True),
    ],
)
async def test_memory_refresh_preserves_live_terminal_flags(
    portrait_world, through_recall, status, sent, pending, locked
):
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState)
            .where(SessionState.session_id == "portrait-session")
            .options(selectinload(SessionState.session))
        )
        owner = state.session.user_id
        state.exit_states = {"terminal": {"game_over_sent": sent}}
        # Model a status change after this ORM session first loaded the relationship.
        await db.execute(
            update(GameSession)
            .where(GameSession.id == state.session_id)
            .values(status=status, status_note="Current status")
            .execution_options(synchronize_session=False)
        )
        await db.commit()
        manager = SimpleNamespace(
            db=db,
            state=state,
            user=SimpleNamespace(id=owner, llm_settings={"memory_rag": {"enabled": True}}),
        )
        if through_recall:
            recall = await prepare_recall(manager, "What happened?", [])
            assert recall.enabled
        else:
            await collect_documents(db, state, owner)

        queries = []

        def record(*args):
            queries.append(args[2])

        engine = db.bind.sync_engine
        event.listen(engine, "before_cursor_execute", record)
        try:
            flags = TurnSessionStateHelper(
                manager,
                gm_notes_state_key="notes",
                gm_notes_max_items=10,
                terminal_epilogue_state_key="terminal",
            ).build_terminal_flags_payload()
        finally:
            event.remove(engine, "before_cursor_execute", record)
        assert flags == {
            "game_over": status == "game_over",
            "game_completed": status == "completed",
            "status_note": "Current status",
            "input_locked": locked,
            "pending_terminal_epilogue": pending,
        }
        assert "session" not in inspect(state).unloaded
        assert not queries, "Formatting terminal flags must not perform SQL"
