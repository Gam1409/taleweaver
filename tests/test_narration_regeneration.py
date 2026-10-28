"""Regeneration preserves committed state and the original response on failure."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from backend.api.routes.adventures import regeneration
from backend.engine.visual_novel.concurrency import session_write_lease
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]
PATH = "/api/adventures/portrait-session/chat/regenerate"


@pytest.fixture
async def narration(portrait_world, monkeypatch):
    async with TestSessionLocal() as db:
        message = ChatMessage(
            session_id="portrait-session", role="assistant", content="The gate remains locked."
        )
        db.add(message)
        await db.commit()
        message_id = message.id
    llm = MagicMock(model="test-model")
    llm.aexecute_simple_task = AsyncMock(return_value="The locked gate refuses to budge.")
    monkeypatch.setattr(regeneration.GameMasterLLM, "for_role", lambda *_: llm)
    return message_id, llm


async def test_regeneration_replaces_message_without_changing_state(auth_client, narration):
    message_id, llm = narration
    async with TestSessionLocal() as db:
        before = (await db.execute(select(SessionState.__table__))).mappings().all()
    response = await auth_client.post(PATH, json={"message_id": message_id})
    assert response.status_code == 200, response.text
    assert response.json()["id"] == message_id
    assert response.json()["content"] == "The locked gate refuses to budge."
    async with TestSessionLocal() as db:
        assert (await db.get(ChatMessage, message_id)).content == response.json()["content"]
        assert (await db.execute(select(SessionState.__table__))).mappings().all() == before
        assert len(list((await db.scalars(select(ChatMessage))).all())) == 1
    llm.aexecute_simple_task.assert_awaited_once()


@pytest.mark.parametrize("failure", [RuntimeError("offline"), TimeoutError(), "   "])
async def test_failed_generation_preserves_original(auth_client, narration, failure):
    message_id, llm = narration
    if isinstance(failure, Exception):
        llm.aexecute_simple_task.side_effect = failure
    else:
        llm.aexecute_simple_task.return_value = failure
    response = await auth_client.post(PATH, json={"message_id": message_id})
    assert response.status_code in {502, 504}
    async with TestSessionLocal() as db:
        assert (await db.get(ChatMessage, message_id)).content == "The gate remains locked."


async def test_stale_and_busy_requests_do_not_call_model(auth_client, narration):
    message_id, llm = narration
    response = await auth_client.post(PATH, json={"message_id": "stale"})
    assert response.status_code == 409
    with session_write_lease("portrait-session"):
        response = await auth_client.post(PATH, json={"message_id": message_id})
    assert response.status_code == 409
    llm.aexecute_simple_task.assert_not_awaited()


async def test_pending_user_action_cannot_regenerate_previous_response(auth_client, narration):
    message_id, llm = narration
    async with TestSessionLocal() as db:
        db.add(ChatMessage(session_id="portrait-session", role="user", content="Try the key."))
        await db.commit()
    response = await auth_client.post(PATH, json={"message_id": message_id})
    assert response.status_code == 409
    llm.aexecute_simple_task.assert_not_awaited()


async def test_foreign_session_is_not_disclosed(auth_client, narration):
    message_id, llm = narration
    response = await auth_client.post(
        "/api/adventures/other-session/chat/regenerate", json={"message_id": message_id}
    )
    assert response.status_code == 404
    llm.aexecute_simple_task.assert_not_awaited()
