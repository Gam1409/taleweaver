"""Periodic NPC summaries retain source clocks and do not replace exact history."""

import json
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.engine.memory_rag import documents, summaries
from backend.engine.memory_rag.documents import _bounded_document, collect_documents
from backend.engine.memory_rag.prompts import MAX_RECALL_CHARS, project
from backend.engine.memory_rag.summary_parts import bounded_parts
from backend.engine.npc_journal import queue, worker
from backend.engine.npc_journal.clock import clock_fields
from backend.engine.npc_journal.lifecycle import remap_journal
from backend.engine.npc_journal.records import journal_of
from backend.engine.npc_journal.schema import JournalExtraction
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.test_memory_rag_retrieval import document
from tests.test_npc_journal import (
    introduction,
    journal_world,
    npc_by_id,
    observation,
    portrait_world,
    save_message,
)
from tests.test_vn_time import ClockRoles
from tests.test_vn_turn_integration import final_payload, install_roles, seed_vn

__all__ = ["journal_world", "portrait_world"]


def facts(count):
    return [document(str(i), text=f"Fact {i}.") for i in range(count)]


def test_npc_summary_waits_for_twenty_relevant_source_replies():
    key = ("npc_summary", "LINA", None)
    assert summaries._job(facts(19), key, []) is None
    job = summaries._job(facts(20), key, [])
    assert job is not None and len(job.message_ids) == 20
    assert len(json.loads(job.prompt)) == 20
    story = [replace(doc, layer="dialogue", npc_id=None) for doc in facts(8)]
    assert summaries._job(story, ("story_summary", None, None), []) is not None


def test_many_facts_from_one_reply_do_not_pretend_to_be_twenty_turns():
    sources = [replace(doc, source_message_ids=["one-reply"]) for doc in facts(40)]
    assert summaries._job(sources, ("npc_summary", "LINA", None), []) is None


def test_dense_npc_history_can_fill_a_bounded_job_before_twenty_replies():
    sources = [replace(doc, text=doc.text * 300) for doc in facts(10)]
    job = summaries._job(sources, ("npc_summary", "LINA", None), [])
    assert job is not None and len(job.prompt) <= summaries.MAX_INPUT_CHARS
    assert 0 < len(job.message_ids) < 20


@pytest.mark.parametrize("count", [20, 200, 2000])
def test_summary_input_stays_bounded_and_does_not_delete_the_original_history(count):
    sources = facts(count)
    before = list(sources)
    job = summaries._job(sources, ("npc_summary", "LINA", None), [])
    assert job is not None
    assert len(job.message_ids) <= summaries.MAX_EVENTS
    assert len(job.prompt) <= summaries.MAX_INPUT_CHARS
    assert sources == before and len(sources) == count


def test_similar_events_keep_their_npc_scene_topic_and_time_anchors():
    sources = [
        replace(
            doc,
            text="She promised to bring the key.",
            scene_id="LAB" if index % 2 else "HALL",
            topic="return_key",
            game_minute=index * 1440,
        )
        for index, doc in enumerate(facts(20))
    ]
    sources.append(replace(sources[0], npc_id="MIKI", source_id="foreign-character"))
    job = summaries._job(sources, ("npc_summary", "LINA", None), [])
    rows = json.loads(job.prompt)
    assert {row["npc_id"] for row in rows} == {"LINA"}
    assert {row["scene_id"] for row in rows} == {"LAB", "HALL"}
    assert [row["game_minute"] for row in rows] == [i * 1440 for i in range(20)]
    assert all(row["topic"] == "return_key" for row in rows)


@pytest.mark.parametrize("value", [None, False, -1, "25", 1.5])
def test_recording_clock_never_invents_a_minute_from_invalid_metadata(value):
    assert clock_fields({"game_minute": value}) == {}


@pytest.mark.parametrize(
    "text", ["x" * 11900, "\x00" * 2500], ids=["near_limit", "escaped_controls"]
)
def test_metadata_and_json_escaping_cannot_make_a_valid_source_unsummarizable(text):
    raw = document("large", text=text, topic="t" * 80)
    parts = _bounded_document(raw)
    covered = set()
    for part in parts:
        start = int(part.source_id.rsplit(":chunk:", 1)[1])
        assert part.text == text[start : start + len(part.text)]
        covered.update(range(start, start + len(part.text)))
    assert len(covered) == len(text)
    sources = parts + [replace(doc, text="tail " * 100) for doc in facts(20)]
    job = summaries._job(sources, ("npc_summary", "LINA", None), [])
    assert job is not None and len(job.prompt) <= summaries.MAX_INPUT_CHARS
    assert json.loads(job.prompt)[0]["text"] == sources[0].text


def test_changed_fragment_boundaries_invalidate_the_embedding_source_hash(monkeypatch):
    raw = document("large", text="A long remembered incident. " * 1000)
    wide = _bounded_document(raw)[0]
    monkeypatch.setattr(documents, "DIALOGUE_CHUNK_CHARS", 1250)
    narrow = _bounded_document(raw)[0]
    assert wide.source_id == narrow.source_id and wide.text != narrow.text
    assert wide.source_hash != narrow.source_hash


def test_summary_source_metadata_separates_game_clock_wall_clock_and_epistemic_tags():
    source = replace(document(), game_minute=0, topic="promise", significance="commitment")
    _, text = bounded_parts([source], 12000, 24)
    row = json.loads(text)[0]
    assert row["game_minute"] == 0 and row["recorded_at"] == "2020-01-01"
    assert row["npc_id"] == "LINA" and row["scene_id"] == "HALL"
    assert row["topic"] == "promise" and row["provenance"] == "claimed"
    assert row["significance"] == "commitment" and row["source_key"] == source.source_id
    block, _ = project([source])
    assert '"game_minute":0' in block and len(block) <= MAX_RECALL_CHARS
    _, legacy = bounded_parts([document()], 12000, 24)
    assert "game_minute" not in json.loads(legacy)[0]


@pytest.mark.asyncio
async def test_completed_reply_stamps_its_clock_before_background_learning(monkeypatch):
    install_roles(monkeypatch, ClockRoles(30))
    async with TestSessionLocal() as db:
        user, _, state, _ = await seed_vn(db)
        events = [
            chunk async for chunk in GameTurnManager(db, "session-1", user).process_turn("Wait.")
        ]
        assert final_payload(events)["status"] == "success"
        reply = await db.scalar(
            select(ChatMessage)
            .where(ChatMessage.session_id == state.session_id, ChatMessage.role == "assistant")
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(1)
        )
        assert state.in_game_time == reply.npc_journal["game_minute"] == 30


@pytest.mark.asyncio
@pytest.mark.parametrize("source_minute", [25, 0, None])
async def test_delayed_learning_and_rag_use_the_source_clock_not_the_workers_current_time(
    journal_world, monkeypatch, source_minute
):
    owner, _ = journal_world
    message_id = await save_message()
    async with TestSessionLocal() as db:
        message = await db.get(ChatMessage, message_id)
        if source_minute is not None:
            message.npc_journal = {**message.npc_journal, "game_minute": source_minute}
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == message.session_id)
        )
        state.in_game_time = 4320
        await db.commit()
    result = JournalExtraction(characters=[introduction(observations=[observation()])])
    monkeypatch.setattr(worker, "extract", AsyncMock(return_value=result))
    assert await worker.process_message(message_id, owner)
    async with TestSessionLocal() as db:
        message = await db.get(ChatMessage, message_id)
        assert message.npc_journal["status"] == "done"
        assert message.npc_journal.get("game_minute") == source_minute
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == message.session_id)
        )
        docs = await collect_documents(db, state, owner)
        doc = next(doc for doc in docs if doc.layer == "npc_journal")
        assert doc.game_minute == source_minute
        npc = await npc_by_id(doc.npc_id)
        original = journal_of(npc, full=True)["entries"][0]
        assert original.get("game_minute") == source_minute
        copied = remap_journal(npc.metadata_json, {message_id: "copy-message"})
        entry = copied["npc_journal"]["entries"][0]
        assert entry.get("game_minute") == source_minute and entry["message_id"] == "copy-message"


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["deferred", "failed", "dependent"])
async def test_work_queue_preserves_the_original_recording_clock(journal_world, outcome):
    message_id = await save_message()
    async with TestSessionLocal() as db:
        message = await db.get(ChatMessage, message_id)
        message.npc_journal = {**message.npc_journal, "game_minute": 37}
        await db.commit()
        task = await queue.claim(db, message)
        assert task["game_minute"] == 37
    if outcome == "deferred":
        await worker._defer(message_id, task)
    elif outcome == "failed":
        await worker._fail(message_id, task)
    else:
        async with TestSessionLocal() as db:
            message = await db.get(ChatMessage, message_id)
            message.npc_journal = {"status": "done", "gaps": ["earlier"], "game_minute": 37}
            await db.commit()
            recovered = ChatMessage(id="earlier", session_id=message.session_id)
            await queue.requeue_dependents(db, recovered)
            await db.commit()
    async with TestSessionLocal() as db:
        assert (await db.get(ChatMessage, message_id)).npc_journal["game_minute"] == 37
