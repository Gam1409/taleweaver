"""Retained narration revisions cannot revive unsupported checkpoint evidence."""

from copy import deepcopy

import pytest
from sqlalchemy import select

from backend.engine.npc_journal import worker
from backend.engine.npc_journal.archive import compact
from backend.engine.npc_journal.records import journal_of, memory_context
from backend.engine.session_checkpoint_service import SessionCheckpointService
from backend.models.chat import ChatMessage
from backend.models.session_checkpoint import SessionCheckpoint
from backend.models.session_state import SessionState
from tests.checkpoint_source_support import (
    ORIGINAL,
    REPLACEMENT,
    actor,
    check_retracted,
    narration,
    observed_reply,
    portrait_world,
)
from tests.conftest import TestSessionLocal

__all__ = ["narration", "observed_reply", "portrait_world"]


async def checkpoint(*, legacy=False):
    async with TestSessionLocal() as db:
        point = await SessionCheckpointService.create_checkpoint(db, "portrait-session", "MANUAL")
        if legacy:
            point.state_snapshot = {
                key: value
                for key, value in point.state_snapshot.items()
                if key != "source_revisions"
            }
        await db.commit()
        return point.id


async def restore(client, checkpoint_id):
    response = await client.post(
        f"/api/adventures/sessions/portrait-session/checkpoints/{checkpoint_id}/restore"
    )
    assert response.status_code == 200, response.text
    assert response.json()["deleted_messages"] == 0


@pytest.mark.parametrize("legacy", [False, True])
async def test_regenerated_retained_source_retracts_restored_evidence(
    auth_client, observed_reply, legacy
):
    source_id, llm = observed_reply
    point = await checkpoint(legacy=legacy)
    response = await auth_client.post(
        "/api/adventures/portrait-session/chat/regenerate", json={"message_id": source_id}
    )
    assert response.status_code == 200, response.text
    revision = response.json()["revision_id"]
    for _ in range(2):
        await restore(auth_client, point)
        await check_retracted("portrait-session", source_id)
        async with TestSessionLocal() as db:
            message = await db.get(ChatMessage, source_id)
            assert (message.content, message.revision_id) == (REPLACEMENT, revision)
            assert len(message.versions) == 2
            assert "smith" not in memory_context(await actor(db))
        card = await auth_client.get("/api/adventures/portrait-session/npcs/NPC_NEW")
        assert card.status_code == 200
        assert [entry["id"] for entry in card.json()["entries"]] == ["earlier"]
    llm.aexecute_simple_task.assert_awaited_once()
    assert worker.schedule.call_count == 2


@pytest.mark.parametrize("legacy", [False, True])
async def test_matching_source_and_manual_description_remain_intact(
    auth_client, observed_reply, legacy
):
    source_id, llm = observed_reply
    async with TestSessionLocal() as db:
        npc = await actor(db)
        npc.description = "Manually authored clothing"
        before = deepcopy(npc.metadata_json)
        await db.commit()
    point = await checkpoint(legacy=legacy)
    await restore(auth_client, point)
    async with TestSessionLocal() as db:
        npc = await actor(db)
        assert npc.description == "Manually authored clothing"
        assert npc.metadata_json == before
        assert (await db.get(ChatMessage, source_id)).content == ORIGINAL
    llm.aexecute_simple_task.assert_not_awaited()
    worker.schedule.assert_not_called()


async def test_anchors_cover_referenced_sources_without_unrelated_transcript(observed_reply):
    source_id, _ = observed_reply
    async with TestSessionLocal() as db:
        db.add(ChatMessage(session_id="portrait-session", role="assistant", content="Unreferenced"))
        await db.commit()
    point = await checkpoint()
    async with TestSessionLocal() as db:
        snapshot = (await db.get(SessionCheckpoint, point)).state_snapshot
        anchors = snapshot.get("source_revisions")
        assert isinstance(anchors, dict)
        expected = {entry["message_id"] for entry in journal_of(await actor(db))["entries"]}
        assert set(anchors) == expected and source_id in anchors
        assert all(set(anchor) == {"revision_id", "content_hash"} for anchor in anchors.values())
        assert ORIGINAL not in str(anchors)
        assert len(list(await db.scalars(select(ChatMessage)))) == 3


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("change", ["missing", "foreign"])
async def test_missing_or_foreign_source_never_revives_derived_evidence(
    auth_client, observed_reply, legacy, change
):
    source_id, llm = observed_reply
    point = await checkpoint(legacy=legacy)
    async with TestSessionLocal() as db:
        message = await db.get(ChatMessage, source_id)
        if change == "missing":
            await db.delete(message)
        else:
            message.session_id = "other-session"
        await db.commit()
    await restore(auth_client, point)
    async with TestSessionLocal() as db:
        npc = await actor(db)
        assert npc is not None and npc.image_url
        assert npc.description == ""
        assert [row["id"] for row in journal_of(npc)["entries"]] == ["earlier"]
        if change == "foreign":
            message = await db.get(ChatMessage, source_id)
            assert message.npc_journal == {"status": "done", "attempts": 1}
            assert message.content == ORIGINAL
    llm.aexecute_simple_task.assert_not_awaited()


async def test_batched_archived_sources_all_save_and_reload(observed_reply):
    async with TestSessionLocal() as db:
        messages = [
            ChatMessage(session_id="portrait-session", role="assistant", content=f"Fact {index}.")
            for index in range(260)
        ]
        db.add_all(messages)
        await db.flush()
        npc = await actor(db)
        journal = journal_of(npc, full=True)
        journal["entries"] = [
            {
                "id": message.id,
                "message_id": message.id,
                "text": message.content,
                "evidence": message.content,
            }
            for message in messages
        ]
        npc.metadata_json = {"npc_journal": compact(journal)}
        await db.commit()
    point = await checkpoint()
    async with TestSessionLocal() as db:
        snapshot = (await db.get(SessionCheckpoint, point)).state_snapshot
        assert len(snapshot["source_revisions"]) == 261
        assert snapshot["canonical_actors"][0]["metadata_json"]["npc_journal"]["archive"]
        before = deepcopy((await actor(db)).metadata_json)
        await SessionCheckpointService.restore_checkpoint(db, "portrait-session", point)
        await db.commit()
    async with TestSessionLocal() as db:
        assert (await actor(db)).metadata_json == before
        assert len(journal_of(await actor(db), full=True)["entries"]) == 260


async def test_invalid_new_anchor_rejected_before_world_mutation(observed_reply):
    point = await checkpoint()
    async with TestSessionLocal() as db:
        saved = await db.get(SessionCheckpoint, point)
        saved.state_snapshot = {
            **saved.state_snapshot,
            "source_revisions": {"source": {"content_hash": "bad"}},
        }
        (await actor(db)).description = "Current manual description"
        await db.commit()
    async with TestSessionLocal() as db:
        with pytest.raises(ValueError, match="source revisions"):
            await SessionCheckpointService.restore_checkpoint(db, "portrait-session", point)
        assert (await actor(db)).description == "Current manual description"


@pytest.mark.parametrize("legacy", [False, True])
async def test_changed_journal_source_retracts_private_causal_suffix(
    auth_client, observed_reply, legacy
):
    from backend.engine.chpm.kernel import digest
    from backend.engine.chpm.schema import KernelState
    from backend.engine.chpm.state import KEY, load
    from tests.test_chpm_host_state import mind, record, source

    source_id, _ = observed_reply
    async with TestSessionLocal() as db:
        message = await db.get(ChatMessage, source_id)
        earlier = await db.scalar(
            select(ChatMessage).where(ChatMessage.content == "Mira likes tea.")
        )
        cognition = mind("NPC_NEW", "portrait-session")
        for minute, row in enumerate([earlier, message], 1):
            binding = source(row.id, text=row.content).model_copy(
                update={
                    "revision_id": row.revision_id,
                    "content_hash": digest(row.content),
                    "speaker_id": "NPC_NEW",
                }
            )
            cognition = record(cognition, binding, minute=minute)
        identity = cognition.genesis.identity
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        state.entity_states = {
            **state.entity_states,
            KEY: KernelState(minds={"NPC_NEW": cognition}).model_dump(mode="json"),
        }
        await db.commit()
    point = await checkpoint(legacy=legacy)
    response = await auth_client.post(
        "/api/adventures/portrait-session/chat/regenerate", json={"message_id": source_id}
    )
    assert response.status_code == 200, response.text
    await restore(auth_client, point)
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        saved = load(state).minds["NPC_NEW"]
        assert saved.genesis.identity == identity
        assert saved.snapshot.cursor == 1
        assert {binding.message_id for binding in saved.sources.values()} == {earlier.id}
