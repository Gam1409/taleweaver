"""Display-only debug toggles must not replace the latest story or its replay snapshot."""

from copy import deepcopy

import pytest

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.api.routes.adventures.turn_replay import replay_status
from backend.models.chat import ChatMessage
from backend.models.turn_replay import TurnReplay
from tests.conftest import TestSessionLocal
from tests.test_narration_regeneration import narration
from tests.test_session_portraits import portrait_world
from tests.test_turn_replay import complete, fake_cycle, seed

__all__ = ["narration", "portrait_world"]
pytestmark = pytest.mark.asyncio


async def test_rewrite_ignores_legacy_debug_toggles_before_applying_history_limit(
    auth_client, narration
):
    message_id, llm = narration
    async with TestSessionLocal() as db:
        for index in range(20):
            db.add(ChatMessage(session_id="portrait-session", role="user", content="/debug on"))
            db.add(
                ChatMessage(session_id="portrait-session", role="system", content=f"Debug {index}")
            )
        await db.commit()
    response = await auth_client.post(
        "/api/adventures/portrait-session/chat/regenerate", json={"message_id": message_id}
    )
    assert response.status_code == 200, response.text
    assert response.json()["id"] == message_id
    assert "/debug on" not in str(llm.aexecute_simple_task.await_args)


@pytest.mark.parametrize("toggles", [["on"], ["on", "off"], ["on", "off", "log on"]])
async def test_actual_toggles_keep_replay_snapshot_and_current_debug_setting(monkeypatch, toggles):
    monkeypatch.setattr(GameTurnManager, "_run_llm_cycle", fake_cycle)
    async with TestSessionLocal() as db:
        user, _, state = await seed(db)
        message_id = await complete(db, user)
        replay = await db.get(TurnReplay, "session-1")
        before = deepcopy(replay.before)
        for toggle in toggles:
            manager = GameTurnManager(db, "session-1", user)
            chunks = [chunk async for chunk in manager.process_turn("/debug " + toggle)]
            assert not any(chunk.startswith("event: error") for chunk in chunks), chunks
        await db.refresh(replay)
        assert replay.status == "ready" and replay.assistant_id == message_id
        assert replay.before == before and replay.input_text == "Я открываю дверь."
        assert (await replay_status("session-1", db, user))["available"]
        await db.refresh(state)
        expected_debug = state.is_debug_enabled
        manager = GameTurnManager(db, "session-1", user)
        chunks = [
            chunk async for chunk in manager.process_turn("ignored", replay_message_id=message_id)
        ]
        assert not any(chunk.startswith("event: error") for chunk in chunks), chunks
        assert manager.state.is_debug_enabled == expected_debug
        assert manager.avatar.hp == 90 and manager.state.in_game_time == 5
