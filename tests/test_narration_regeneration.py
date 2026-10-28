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
    monkeypatch.setattr(regeneration, "schedule", MagicMock())
    monkeypatch.setattr(regeneration, "queue_refresh", MagicMock())
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


async def test_regeneration_uses_configured_model_deadline(auth_client, narration, monkeypatch):
    message_id, _ = narration
    original_wait = regeneration.asyncio.wait_for
    observed = []

    async def wait(awaitable, timeout):
        if getattr(awaitable, "__name__", "") == "generate_narration":
            observed.append(timeout)
        return await original_wait(awaitable, timeout)

    monkeypatch.setattr(
        regeneration, "role_timeout", lambda user, role: 600 if role == "complex" else 5
    )
    monkeypatch.setattr(regeneration.asyncio, "wait_for", wait)
    response = await auth_client.post(PATH, json={"message_id": message_id})
    assert response.status_code == 200
    assert observed == [600]


async def test_concurrent_new_message_rejects_stale_rewrite(auth_client, narration):
    message_id, llm = narration

    async def reply(*args, **kwargs):
        # This commit also proves that inference does not hold a SQLite writer.
        async with TestSessionLocal() as db:
            db.add(ChatMessage(session_id="portrait-session", role="user", content="Next action"))
            await db.commit()
        return "Replacement"

    llm.aexecute_simple_task.side_effect = reply
    response = await auth_client.post(PATH, json={"message_id": message_id})
    assert response.status_code == 409
    async with TestSessionLocal() as db:
        assert (await db.get(ChatMessage, message_id)).content == "The gate remains locked."


async def test_rewrite_refreshes_visuals_and_memory_without_deleting_npc(auth_client, narration):
    from backend.engine.scene_illustrations.context import illustration_status
    from backend.engine.scene_illustrations.snapshots import REGISTRY_KEY, content_hash
    from backend.models.memory_rag import MemoryIndexState, MemorySummary
    from backend.models.world_entity import WorldEntity

    message_id, _ = narration
    async with TestSessionLocal() as db:
        message = await db.get(ChatMessage, message_id)
        message.npc_journal = {"status": "done", "attempts": 1}
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        session = await db.get(regeneration.GameSession, "portrait-session")
        state.entity_states = {
            **state.entity_states,
            REGISTRY_KEY: {
                "snapshots": {
                    message_id: {
                        "content_hash": content_hash(message),
                        "visible_facts": {"setting": "Gate"},
                        "narration": message.content,
                    }
                },
                "images": {
                    message_id: {"content_hash": content_hash(message), "image_url": "/old.png"}
                },
            },
        }
        npc = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == session.id, WorldEntity.id == "NPC_NEW"
            )
        )
        npc.metadata_json = {
            "npc_journal": {
                "origin": "introduced",
                "introduced_message_id": message_id,
                "entries": [
                    {"message_id": message_id, "text": "Old extracted detail"},
                    {"message_id": "earlier", "text": "Earlier detail"},
                ],
            }
        }
        db.add(
            MemoryIndexState(
                session_id=session.id, user_id=session.user_id, epoch=4, lease_token="old-job"
            )
        )
        for key, sources in [("affected", [message_id]), ("unrelated", ["earlier"])]:
            db.add(
                MemorySummary(
                    id=key,
                    session_id=session.id,
                    user_id=session.user_id,
                    layer="story_summary",
                    text="Summary",
                    source_message_ids=sources,
                    source_hash="old",
                )
            )
        await db.commit()
    response = await auth_client.post(PATH, json={"message_id": message_id})
    assert response.status_code == 200, response.text
    async with TestSessionLocal() as db:
        message = await db.get(ChatMessage, message_id)
        assert message.npc_journal == {"status": "pending", "attempts": 0}
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        status = illustration_status(state, message)
        assert status["available"] and status["image_url"] is None
        assert state.entity_states[REGISTRY_KEY]["snapshots"][message_id]["visible_facts"] == {
            "setting": "Gate"
        }
        npc = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == "portrait-session", WorldEntity.id == "NPC_NEW"
            )
        )
        assert npc is not None and npc.image_url
        assert npc.metadata_json["npc_journal"]["entries"] == [
            {"message_id": "earlier", "text": "Earlier detail"}
        ]
        index = await db.get(MemoryIndexState, "portrait-session")
        assert index.epoch == 5 and index.lease_token is None
        assert await db.get(MemorySummary, "affected") is None
        assert await db.get(MemorySummary, "unrelated") is not None
    regeneration.schedule.assert_called_once()
    regeneration.queue_refresh.assert_called_once()


@pytest.mark.parametrize("enabled", [False, True])
async def test_rewrite_uses_saved_vn_pace_and_optional_addendum(
    auth_client, narration, monkeypatch, enabled
):
    from backend.core import mature_content_prompts
    from backend.models.adventure_template import AdventureTemplate

    message_id, llm = narration
    monkeypatch.setattr(
        mature_content_prompts, "NARRATIVE_ADDENDUM", "OPTIONAL NARRATION TEST MARKER"
    )
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, "portrait-template")
        adventure.rule_enforcement_mode = "vn"
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        state.entity_states = {
            **state.entity_states,
            "__vn_settings__": {"pace": "leisurely"},
            "__manifest_snapshot__": {
                "original_manifest": {"clothing_settings": {"detailed": enabled}}
            },
        }
        await db.commit()
    response = await auth_client.post(PATH, json={"message_id": message_id})
    assert response.status_code == 200, response.text
    system = llm.aexecute_simple_task.call_args.args[0]
    assert "VISUAL NOVEL NARRATION CONTRACT" in system
    assert "PACING: LEISURELY" in system
    assert ("OPTIONAL NARRATION TEST MARKER" in system) is enabled
    assert "CURRENT NPC PRESENCE" in system
