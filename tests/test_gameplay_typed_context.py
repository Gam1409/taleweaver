"""Type refinements preserve detached adventures and legacy chronicle summaries."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.api.routes.adventures.adventure_snapshot import AdventureSnapshot
from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.api.routes.adventures.logic import AdventureLogic
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.test_game_loop import _seed_game_context


@pytest.mark.asyncio
async def test_deleted_template_uses_detached_snapshot_for_script_context():
    async with TestSessionLocal() as db:
        user, adventure, avatar, state = await _seed_game_context(db)
        state.entity_states = {
            "__manifest_snapshot__": AdventureLogic.build_session_manifest_snapshot(adventure)
        }
        await db.refresh(state, attribute_names=["session"])
        state.session.template_id = None
        state.template_id = None
        avatar.template_id = None
        await db.delete(adventure)
        await db.commit()

        manager = GameTurnManager(db, state.session_id, user)
        assert await manager.initialize()
        assert isinstance(manager.adventure, AdventureSnapshot)
        assert manager.adventure.title == "Test Adventure"
        assert manager.adventure.id == "adv-1"
        context = await manager._build_script_context()
        assert context.player.name == "Hero"


@pytest.mark.asyncio
async def test_legacy_string_summary_is_preserved_during_compression(monkeypatch):
    async with TestSessionLocal() as db:
        user, adventure, avatar, state = await _seed_game_context(db)
        state.max_memory_turns = 1
        state.compressed_history = "The hero found a silver key."
        db.add_all(
            [
                ChatMessage(session_id=state.session_id, role="user", content="Open the gate."),
                ChatMessage(
                    session_id=state.session_id, role="assistant", content="The gate opens."
                ),
                ChatMessage(session_id=state.session_id, role="user", content="Step outside."),
            ]
        )
        await db.commit()
        summarize = AsyncMock(return_value="The hero used the silver key to open the gate.")
        monkeypatch.setattr(
            "backend.api.routes.adventures.gameplay_logic.GameMasterLLM.for_role",
            lambda *_: SimpleNamespace(model="test", aexecute_simple_task=summarize),
        )
        manager = GameTurnManager(db, state.session_id, user, state, adventure, avatar)
        events = [event async for event in manager._compress_history_if_needed()]
        assert events
        assert "The hero found a silver key." in summarize.call_args.kwargs["user_prompt"]
        assert isinstance(state.compressed_history, dict)
        assert (
            state.compressed_history["summary"] == "The hero used the silver key to open the gate."
        )
        assert state.compressed_history["last_compressed_msg_id"]
