"""Canonical recall keeps evidence, ownership and timeline boundaries intact."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import select

from backend.engine.memory_rag import summaries
from backend.engine.memory_rag.chronicle import _bounded, compress_history_one_group
from backend.engine.memory_rag.documents import collect_documents, validate_candidates
from backend.engine.memory_rag.lifecycle import invalidate_memory, memory_snapshot, restore_memory
from backend.engine.memory_rag.retrieval import prepare_recall
from backend.engine.npc_journal.schema import CharacterObservation
from backend.engine.session_checkpoint_service import SessionCheckpointService
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.memory_rag import MemoryIndexState, MemorySummary
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.test_npc_journal import (
    apply,
    introduction,
    journal_world,
    observation,
    portrait_world,
    save_message,
)

__all__ = ["journal_world", "portrait_world"]


async def _state(db):
    state = await db.scalar(
        select(SessionState).where(SessionState.session_id == "portrait-session")
    )
    state.user_id = await db.scalar(
        select(GameSession.user_id).where(GameSession.id == state.session_id)
    )
    return state


async def test_journal_recall_retains_general_topics_and_rejects_stale_vectors(journal_world):
    first = await save_message()
    npc_id = (await apply(first, [introduction(observations=[observation()])]))[0]
    later = await save_message("Мира сказала: «Я кузнец».")
    await apply(
        later,
        [
            CharacterObservation(
                npc_id=npc_id,
                name="Мира",
                observations=[observation("background", "Кузнец", "Я кузнец")],
            )
        ],
    )
    async with TestSessionLocal() as db:
        state = await _state(db)
        documents = await collect_documents(db, state, state.user_id)
        journal = [doc for doc in documents if doc.layer == "npc_journal"]
        assert len(journal) == 2
        manager = SimpleNamespace(
            db=db,
            state=state,
            user=SimpleNamespace(id=state.user_id, llm_settings={"memory_rag": {"enabled": True}}),
        )
        recall = await prepare_recall(manager, "Кузнец", [])
        assert recall.enabled and any("Кузнец" in doc.text for doc in recall.documents)
        assert await collect_documents(db, state, "another-user") == []
        forged = replace(journal[0], text="forged vector content")
        restored = await validate_candidates(db, state, state.user_id, [forged])
        assert restored[0].text == journal[0].text
        message = await db.get(ChatMessage, later)
        await db.delete(message)
        await db.commit()
        assert await validate_candidates(db, state, state.user_id, [journal[-1]]) == []


async def test_player_dialogue_is_explicitly_unverified_and_private_inventory_absent(journal_world):
    async with TestSessionLocal() as db:
        state = await _state(db)
        db.add(
            ChatMessage(session_id=state.session_id, role="user", content="She gave me her key.")
        )
        await db.commit()
        documents = await collect_documents(db, state, state.user_id)
        claim = next(doc for doc in documents if "She gave me" in doc.text)
        assert claim.provenance == "claimed"
        assert "not verified" in claim.text
        assert all("SECRET" not in doc.text for doc in documents)


async def test_checkpoint_restores_general_memory_and_fences_old_summary_work(journal_world):
    async with TestSessionLocal() as db:
        state = await _state(db)
        state.world_memories = [{"id": "old", "description": "An old promise", "emotion": "trust"}]
        state.compressed_history = {"summary": "The player met Mira."}
        state.enable_history_compression = False
        db.add(
            MemoryIndexState(
                session_id=state.session_id, user_id=state.user_id, epoch=3, lease_token="running"
            )
        )
        checkpoint = await SessionCheckpointService.create_checkpoint(
            db, state.session_id, "manual"
        )
        await db.commit()
        state.world_memories = [{"id": "future", "description": "Future event", "emotion": "anger"}]
        state.compressed_history = {"summary": "Future spoiler."}
        state.enable_history_compression = True
        await db.commit()
        await SessionCheckpointService.restore_checkpoint(db, state.session_id, checkpoint.id)
        await db.commit()
        assert state.world_memories[0]["id"] == "old"
        assert state.compressed_history["summary"] == "The player met Mira."
        assert state.enable_history_compression is False
        control = await db.get(MemoryIndexState, state.session_id)
        assert control.epoch == 4 and control.lease_token is None


def test_copy_remaps_chronicle_cursor_and_preserves_memory_settings():
    original = SimpleNamespace(
        world_memories=[{"id": "one"}],
        world_rumors=[],
        compressed_history={"summary": "past", "last_compressed_msg_id": "old"},
        enable_history_compression=False,
    )
    copied = SimpleNamespace()
    restore_memory(copied, memory_snapshot(original), {"old": "new"})
    assert copied.compressed_history["last_compressed_msg_id"] == "new"
    assert copied.world_memories == original.world_memories
    assert copied.enable_history_compression is False


async def test_summary_job_is_bounded_and_rejects_changed_sources(journal_world, monkeypatch):
    for index in range(8):
        await save_message(f"Mira kept promise number {index}.")
    model = SimpleNamespace(
        model="fake", aexecute_simple_task=AsyncMock(return_value="Mira kept promises.")
    )
    monkeypatch.setattr(summaries.GameMasterLLM, "for_role", lambda *_: model)
    monkeypatch.setattr(summaries.scheduler, "can_start_background", lambda: True)
    async with TestSessionLocal() as db:
        state = await _state(db)
        db.add(
            MemoryIndexState(
                session_id=state.session_id, user_id=state.user_id, epoch=0, lease_token="lease"
            )
        )
        await db.commit()
        assert await summaries.summarize_one_group(
            db, SimpleNamespace(id=state.user_id), state, epoch=0, lease_token="lease"
        )
        row = await db.scalar(
            select(MemorySummary).where(MemorySummary.session_id == state.session_id)
        )
        assert len(row.source_message_ids) == 8
        assert model.aexecute_simple_task.await_count == 1
        documents = await collect_documents(db, state, state.user_id)
        assert any(doc.provenance == "summary" for doc in documents)
        message = await db.get(ChatMessage, row.source_message_ids[0])
        message.content = "The source was corrected."
        await db.commit()
        documents = await collect_documents(db, state, state.user_id)
        assert not any(doc.layer == row.layer for doc in documents)


def test_large_message_compression_cursor_never_skips_unprocessed_tail():
    row = SimpleNamespace(id="long", role="assistant", content="a" * 16000)
    first = _bounded([row], {})
    assert first["last_compressed_msg_id"] is None
    assert first["pending_message_id"] == "long"
    assert len(first["events"]) <= 12000
    second = _bounded([row], first)
    assert second["last_compressed_msg_id"] == "long"
    assert second["pending_message_id"] is None
    assert first["events"].count("a") + second["events"].count("a") >= 16000


async def test_legacy_compression_runs_while_vectors_paused(journal_world, monkeypatch):
    model = SimpleNamespace(
        model="fake", aexecute_simple_task=AsyncMock(return_value="An updated chronicle.")
    )
    monkeypatch.setattr(summaries.GameMasterLLM, "for_role", lambda *_: model)
    monkeypatch.setattr(summaries.scheduler, "can_start_background", lambda: True)
    async with TestSessionLocal() as db:
        state = await _state(db)
        state.max_memory_turns = 1
        state.compressed_history = {"summary": "An older promise."}
        for index in range(5):
            db.add(
                ChatMessage(session_id=state.session_id, role="user", content=f"Question {index}")
            )
            db.add(
                ChatMessage(
                    session_id=state.session_id, role="assistant", content=f"Answer {index}"
                )
            )
            await db.flush()
        db.add(
            MemoryIndexState(
                session_id=state.session_id,
                user_id=state.user_id,
                epoch=0,
                lease_token="lease",
                paused=True,
            )
        )
        await db.commit()
        assert await compress_history_one_group(
            db, SimpleNamespace(id=state.user_id), state, epoch=0, lease_token="lease"
        )
        assert "An older promise." in model.aexecute_simple_task.call_args.kwargs["user_prompt"]
        await db.refresh(state, attribute_names=["compressed_history"])
        assert state.compressed_history["summary"] == "An updated chronicle."


async def test_export_import_preserves_general_memory(auth_client, journal_world):
    async with TestSessionLocal() as db:
        state = await _state(db)
        state.world_memories = [{"id": "old", "description": "Old fact", "emotion": "trust"}]
        state.compressed_history = {"summary": "Old chronicle."}
        state.enable_history_compression = False
        await db.commit()
    exported = await auth_client.get("/api/adventures/sessions/portrait-session/export")
    assert exported.status_code == 200
    imported = await auth_client.post(
        "/api/adventures/sessions/import",
        files={"file": ("session.ads", exported.content, "application/zip")},
    )
    assert imported.status_code == 200
    async with TestSessionLocal() as db:
        copied = await db.scalar(
            select(SessionState).where(SessionState.session_id == imported.json()["game_id"])
        )
        assert copied.world_memories[0]["id"] == "old"
        assert copied.compressed_history["summary"] == "Old chronicle."
        assert copied.enable_history_compression is False


async def test_summary_intervals_accumulate_without_overwriting_old_evidence(
    journal_world, monkeypatch
):
    model = SimpleNamespace(
        model="fake", aexecute_simple_task=AsyncMock(return_value="The old promise endured.")
    )
    monkeypatch.setattr(summaries.GameMasterLLM, "for_role", lambda *_: model)
    monkeypatch.setattr(summaries.scheduler, "can_start_background", lambda: True)
    for index in range(8):
        await save_message(f"Old promise {index}.")
    async with TestSessionLocal() as db:
        state = await _state(db)
        user = SimpleNamespace(id=state.user_id)
        db.add(
            MemoryIndexState(
                session_id=state.session_id, user_id=user.id, epoch=0, lease_token="lease"
            )
        )
        await db.commit()
        for _ in range(2):
            assert await summaries.summarize_one_group(
                db, user, state, epoch=0, lease_token="lease"
            )
        first = list(await db.scalars(select(MemorySummary)))
        original_sources = {row.id: row.source_message_ids for row in first}
        await db.commit()
        for index in range(8):
            await save_message(f"Later discovery {index}.")
        model.aexecute_simple_task.return_value = "Later discoveries."
        for _ in range(2):
            assert await summaries.summarize_one_group(
                db, user, state, epoch=0, lease_token="lease"
            )
        all_rows = list(await db.scalars(select(MemorySummary)))
        assert len(all_rows) == 4
        assert all(row.source_message_ids == original_sources[row.id] for row in first)
        documents = await collect_documents(db, state, user.id)
        assert sum(doc.text == "The old promise endured." for doc in documents) == 2
        assert model.aexecute_simple_task.await_count == 4
        assert not await summaries.summarize_one_group(
            db, user, state, epoch=0, lease_token="lease"
        )
        assert model.aexecute_simple_task.await_count == 4


async def test_clear_during_summary_call_prevents_canonical_write(journal_world, monkeypatch):
    for index in range(8):
        await save_message(f"Event {index}.")

    async def clear_then_respond(**_kwargs):
        async with TestSessionLocal() as db:
            await invalidate_memory(db, "portrait-session")
            await db.commit()
        return "A result from a stale worker."

    model = SimpleNamespace(
        model="fake", aexecute_simple_task=AsyncMock(side_effect=clear_then_respond)
    )
    monkeypatch.setattr(summaries.GameMasterLLM, "for_role", lambda *_: model)
    monkeypatch.setattr(summaries.scheduler, "can_start_background", lambda: True)
    async with TestSessionLocal() as db:
        state = await _state(db)
        db.add(
            MemoryIndexState(
                session_id=state.session_id, user_id=state.user_id, epoch=0, lease_token="lease"
            )
        )
        await db.commit()
        assert await summaries.summarize_one_group(
            db, SimpleNamespace(id=state.user_id), state, epoch=0, lease_token="lease"
        )
        assert await db.scalar(select(MemorySummary.id)) is None
        assert model.aexecute_simple_task.await_count == 1


async def test_long_dialogue_chunks_are_bounded_and_full_source_edits_invalidate_all(journal_world):
    text = "First promise. " + "story details " * 1800 + " Last important discovery."
    async with TestSessionLocal() as db:
        state = await _state(db)
        message = ChatMessage(session_id=state.session_id, role="user", content=text)
        state.compressed_history = {"summary": "Old story. " * 2000}
        db.add(message)
        await db.commit()
        documents = await collect_documents(db, state, state.user_id)
        chunks = [doc for doc in documents if doc.source_message_ids == [message.id]]
        assert len(chunks) > 1
        assert all(len(doc.text) <= 2600 and doc.provenance == "claimed" for doc in chunks)
        assert all(
            doc.text.startswith("Player statement/action (not verified): ") for doc in chunks
        )
        assert chunks[0].source_id == f"{message.id}:0"
        assert "Last important discovery." in chunks[-1].text
        assert all(len(doc.text) <= 12000 for doc in documents)
        assert len({doc.id for doc in chunks}) == len(chunks)
        repeated = await collect_documents(db, state, state.user_id)
        assert [(doc.id, doc.source_hash) for doc in repeated] == [
            (doc.id, doc.source_hash) for doc in documents
        ]
        message.content = "Changed beginning. " + text[19:]
        await db.commit()
        assert await validate_candidates(db, state, state.user_id, chunks) == []
