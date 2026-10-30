"""Editorial feedback is delivered once without becoming story or mechanics input."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.api.routes.adventures.regeneration import RegenerateRequest
from backend.api.routes.adventures.schemas import ChatRequest
from backend.engine.narration_correction import append_correction
from backend.engine.rule_engine import GameEvent
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.llm_fakes import RoleLLMFactory
from tests.test_game_loop import _seed_game_context
from tests.test_narration_regeneration import PATH, narration, portrait_world

__all__ = ["narration", "portrait_world"]
NOTE = "Use fewer sound tags; do not repeat the same reaction."


def test_correction_keeps_system_prefix_and_does_not_change_empty_requests():
    assert append_correction("Base", None) == "Base"
    assert append_correction("Base", "  ") == "Base"
    prompt = append_correction("Base", NOTE)
    assert prompt.startswith("Base\n\nEDITORIAL CORRECTION")
    assert prompt.endswith(json.dumps(NOTE))
    assert "engine-confirmed facts" in prompt


@pytest.mark.parametrize(
    "schema,fields",
    [(ChatRequest, {"content": "Hi"}), (RegenerateRequest, {"message_id": "reply"})],
)
def test_request_limits_and_normalizes_feedback(schema, fields):
    assert schema(**fields, narration_correction="  Hello  ").narration_correction == "Hello"
    with pytest.raises(ValidationError):
        schema(**fields, narration_correction="x" * 2001)


async def test_rewrite_receives_feedback_only_in_system_and_acknowledges_saved_result(
    auth_client, narration
):
    message_id, llm = narration
    response = await auth_client.post(
        PATH, json={"message_id": message_id, "narration_correction": NOTE}
    )
    assert response.status_code == 200, response.text
    assert response.json()["narration_correction_applied"] is True
    system, context, _ = llm.aexecute_simple_task.call_args.args
    assert system.endswith(json.dumps(NOTE))
    assert NOTE not in context
    async with TestSessionLocal() as db:
        assert all(NOTE not in m.content for m in await db.scalars(select(ChatMessage)))
    await auth_client.post(PATH, json={"message_id": message_id})
    assert NOTE not in llm.aexecute_simple_task.call_args.args[0]


@pytest.mark.parametrize("ending", ["stop", "length", "error", "empty"])
@pytest.mark.parametrize("replay", [False, True])
async def test_turn_and_replay_apply_only_to_narration(monkeypatch, ending, replay):
    llm = MagicMock()
    llm.aexecute_complex_task = AsyncMock(return_value=GameEvent(narrative_description="A reply."))
    current_ending = "stop"

    async def stream():
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content="A quiet reply." if current_ending != "empty" else ""
                    ),
                    finish_reason=None,
                )
            ]
        )
        if current_ending == "error":
            raise ConnectionResetError("provider disconnected")
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=""),
                    finish_reason="stop" if current_ending == "empty" else current_ending,
                )
            ]
        )

    llm.stream_simple_task = AsyncMock(side_effect=lambda *a, **kw: stream())
    monkeypatch.setattr(
        "backend.api.routes.adventures.gameplay_logic.GameMasterLLM",
        RoleLLMFactory(lambda *a, **kw: llm),
    )
    async with TestSessionLocal() as db:
        user, _, _, _ = await _seed_game_context(db)
        replay_id = None
        if replay:
            original = GameTurnManager(db, "session-1", user)
            _ = [chunk async for chunk in original.process_turn("I ask a question")]
            replay_id = await db.scalar(
                select(ChatMessage.id).where(ChatMessage.role == "assistant")
            )
        current_ending = ending
        llm.reset_mock()
        manager = GameTurnManager(db, "session-1", user)
        manager.narration_correction = NOTE
        events = [
            chunk
            async for chunk in manager.process_turn("I ask a question", replay_message_id=replay_id)
        ]
        call = llm.stream_simple_task.call_args
        assert call is not None, events
        assert call.args[0].endswith(json.dumps(NOTE))
        messages = call.kwargs["messages"]
        assert messages[0]["content"].endswith(json.dumps(NOTE))
        assert all(NOTE not in message["content"] for message in messages[1:])
        assert NOTE not in str(llm.aexecute_complex_task.call_args_list)
        finals = [
            json.loads(e.split("data: ", 1)[1]) for e in events if e.startswith("event: final")
        ]
        assert (
            not any(f.get("narration_correction_applied") for f in finals)
            if ending != "stop"
            else finals[-1]["narration_correction_applied"]
        )
        assert all(NOTE not in m.content for m in await db.scalars(select(ChatMessage)))


async def test_route_sets_feedback_on_request_manager_without_modifying_player_action(monkeypatch):
    from backend.api.routes.adventures import gameplay

    observed = []

    async def turn(content, **kwargs):
        observed.append(content)
        yield 'event: final\ndata: {"status":"success"}\n\n'

    manager = SimpleNamespace(process_turn=turn)
    monkeypatch.setattr(gameplay, "GameTurnManager", lambda *args: manager)
    response = await gameplay.post_chat_message(
        "session", ChatRequest(content="Hello", narration_correction=NOTE), None, None
    )
    _ = [chunk async for chunk in response.body_iterator]
    assert manager.narration_correction == NOTE
    assert observed == ["Hello"]
