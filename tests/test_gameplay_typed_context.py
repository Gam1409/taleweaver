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


async def test_debug_item_generation_passes_a_boolean_visualization_flag():
    from backend.api.routes.adventures.turn_interactions import TurnInteractionsManager

    calls = []

    async def cycle(message, auto_visualize, language=None, narration_only=False):
        calls.append((message, auto_visualize))
        yield "generated"

    manager = SimpleNamespace(_run_llm_cycle=cycle)
    interactions = TurnInteractionsManager(manager)
    stream = interactions._handle_debug_gen_item("a silver key")
    assert await anext(stream) == "generated"
    await stream.aclose()
    assert calls[0][1] is True
    assert "a silver key" in calls[0][0]


def test_turn_context_requires_initialized_state_and_avatar():
    from backend.api.routes.adventures.turn_interactions import TurnInteractionsManager

    interactions = TurnInteractionsManager(SimpleNamespace(state=None, avatar=None))
    with pytest.raises(RuntimeError, match="Initialize.*state"):
        _ = interactions.state
    with pytest.raises(RuntimeError, match="Initialize.*avatar"):
        _ = interactions.avatar
