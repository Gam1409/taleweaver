"""Exercise the actual narrator method, mocking only its completion transport."""

import json
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from litellm import ModelResponse
from sqlalchemy import select

from backend.core.llm_router import GameMasterLLM
from backend.engine.chpm import continuation_writer, inference, rendering
from backend.engine.chpm.errors import ChpmError
from backend.engine.chpm.inference import OutputBudgetError
from backend.engine.chpm.schema import KernelState, Settings
from backend.engine.chpm.state import KEY, load
from backend.models.chat import ChatMessage
from backend.models.user import User
from tests.conftest import TestSessionLocal
from tests.test_chpm_fallback import continuing
from tests.test_chpm_turn import ChpmRoles
from tests.test_vn_turn_integration import ACTION, PRIOR, install_roles, seed_vn

FRESH = "Lina: Let us examine the sealed blue vial."


def response(text=FRESH, finish="stop", tokens=12):
    return ModelResponse(
        choices=[{"message": {"role": "assistant", "content": text}, "finish_reason": finish}],
        usage={"prompt_tokens": 100, "completion_tokens": tokens, "total_tokens": 100 + tokens},
    )


@pytest.fixture
def real_narrator(monkeypatch):
    user = User(
        username="offline-narrator",
        llm_settings={
            "ollama_url": "http://localhost:11434",
            "complex_model": "local-narrator",
            "complex_model_provider": "ollama",
        },
        encrypted_api_keys={},
    )
    router = GameMasterLLM.for_role(user, "complex")
    router.max_tokens = 8192
    router.request_timeout = 2
    transport = AsyncMock(return_value=response())
    monkeypatch.setattr(router, "_acompletion_with_openrouter_fallback", transport)
    return router, transport


async def test_legacy_simple_request_keeps_its_system_and_user_messages(real_narrator):
    router, transport = real_narrator
    assert await router.aexecute_simple_task("Policy", "Hello", router.model) == FRESH
    assert transport.call_args.args[0]["messages"] == [
        {"role": "system", "content": "Policy"},
        {"role": "user", "content": "Hello"},
    ]
    transport.assert_awaited_once()


@pytest.mark.parametrize("with_history", [False, True])
async def test_real_fallback_preserves_history_and_replaces_only_current_intentions(
    real_narrator, with_history
):
    router, transport = real_narrator
    host, turn = continuing()
    host._chpm_model_factory = Mock(return_value=router)
    turn.player_request = "Examine the sample."
    turn.fallback_issues = ["An unapproved promise."]
    history = [
        {"role": "system", "content": "Original policy"},
        {"role": "user", "content": "Where is the sample?"},
        {"role": "assistant", "content": "It is sealed in the blue vial."},
        {"role": "user", "content": "REJECTED_CHPM_INTENT"},
    ]
    before = deepcopy(history)
    saved = deepcopy(host.state.entity_states)
    result = await continuation_writer.generate(
        host,
        turn,
        "Resolved action",
        "Original policy",
        narration_messages=history if with_history else None,
        ordinary_context="Current room and confirmed state",
    )
    assert result == FRESH and history == before
    assert host.state.entity_states == saved
    host._chpm_model_factory.assert_called_once_with("complex")
    sent = transport.call_args.args[0]
    assert sent["messages"][:-1] == (history[:-1] if with_history else history[:1])
    payload = json.loads(sent["messages"][-1]["content"])
    assert payload["player_request"] == turn.player_request
    assert payload["current_scene_and_resolution"] == "Current room and confirmed state"
    assert payload["review_issues_to_avoid"] == turn.fallback_issues
    assert "REJECTED_CHPM_INTENT" not in str(sent)
    assert "narration" not in payload
    assert sent["max_tokens"] == 4096 and router.enable_thinking is False
    assert turn.usage.fallback_requests == 1
    with pytest.raises(ChpmError, match="already used"):
        await continuation_writer.generate(host, turn, "Resolved action", "Original policy")
    transport.assert_awaited_once()


@pytest.mark.parametrize("failure", ["truncated", "empty", "timeout"])
async def test_real_fallback_still_rejects_incomplete_output_without_another_request(
    real_narrator, failure
):
    router, transport = real_narrator
    host, turn = continuing()
    host._chpm_model_factory = lambda role: router
    expected = ChpmError
    if failure == "truncated":
        transport.return_value = response("Incomplete", "length", 4096)
        expected = OutputBudgetError
    elif failure == "empty":
        transport.return_value = response("")
    else:
        transport.side_effect = TimeoutError("offline timeout")
        expected = TimeoutError
    with pytest.raises(expected):
        await continuation_writer.generate(host, turn, "Resolved action", "Policy")
    assert turn.simplified_text is None and turn.usage.fallback_requests == 1
    transport.assert_awaited_once()


async def test_rejected_real_turn_commits_only_the_fresh_router_reply(monkeypatch, real_narrator):
    router, transport = real_narrator
    roles = ChpmRoles(reject=True)
    install_roles(monkeypatch, roles)
    monkeypatch.setattr(inference, "GameMasterLLM", roles)
    monkeypatch.setattr(rendering, "GameMasterLLM", roles)
    factory = Mock(return_value=router)
    monkeypatch.setattr(continuation_writer, "GameMasterLLM", SimpleNamespace(for_role=factory))
    async with TestSessionLocal() as db:
        from backend.engine.gameplay.manager import GameTurnManager

        user, _, state, previous_id = await seed_vn(db)
        previous = await db.get(ChatMessage, previous_id)
        # The history window starts at a player-turn boundary, not an orphan reply.
        db.add(
            ChatMessage(
                session_id="session-1",
                role="user",
                content="Let us repair the shelf.",
                scene_id="START",
                created_at=previous.created_at - timedelta(seconds=1),
            )
        )
        state.entity_states = {
            **state.entity_states,
            KEY: KernelState(settings=Settings(mode="live", actor_ids=["LINA"])).model_dump(),
        }
        await db.commit()
        manager = GameTurnManager(db, "session-1", user)
        chunks = [chunk async for chunk in manager.process_turn(ACTION)]
        assert any(chunk.startswith("event: final") for chunk in chunks), "".join(chunks)
        assert not any(chunk.startswith("event: error") for chunk in chunks), "".join(chunks)
        saved = load(manager.state)
        assert saved.usage.fallback_requests == 1 and saved.recovery.pending_gap_turns == 1
        assert saved.minds == {} and saved.actors == {}
        assert roles.chpm_calls.count("validation") == 2
        assert roles.chpm_calls.count("repair") == 1
        replies = list(
            await db.scalars(
                select(ChatMessage).where(
                    ChatMessage.session_id == "session-1", ChatMessage.role == "assistant"
                )
            )
        )
        assert {reply.content for reply in replies} == {PRIOR, FRESH}
        sent = transport.call_args.args[0]["messages"]
        assert any(message["content"] == PRIOR for message in sent)
        assert "CHPM DIALOGUE CONTRACT" not in str(sent)
        assert json.loads(sent[-1]["content"])["review_issues_to_avoid"] == ["Unapproved promise"]
        factory.assert_called_once_with(user, "complex")
        transport.assert_awaited_once()
