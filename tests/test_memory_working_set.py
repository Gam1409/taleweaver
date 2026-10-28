"""A bounded working set complements retrieval without replaying the entire NPC journal."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.diagnostic_fields import safe_fields
from backend.engine.memory_rag import retrieval, worker
from backend.engine.memory_rag.core import context_fallback, working_memory
from backend.engine.memory_rag.prompts import MAX_RECALL_CHARS, project
from backend.engine.npc_journal import progress
from tests.test_memory_rag_retrieval import document


def fact(identifier, npc_id, topic, text, created_at):
    return document(
        identifier,
        npc_id=npc_id,
        topic=topic,
        significance="boundary",
        category="relationship",
        text=text,
        created_at=created_at,
    )


def test_working_set_selects_latest_topic_but_preserves_archive():
    old = fact("old", "RIN", "promise_results", "Results tomorrow", "2026-01-01")
    new = fact("new", "RIN", "promise_results", "The appointment was cancelled", "2026-01-02")
    other = fact("other", "MIKI", "boundary", "Please ask before entering", "2026-01-01")
    absent = fact("absent", "AWAY", "boundary", "Absent person's history", "2026-01-01")
    documents = [old, new, other, absent]
    core = working_memory(documents, {"RIN", "MIKI"})
    assert {doc.id for doc in core} == {"new", "other"}
    block, selected = project(documents, core_documents=core)
    assert {doc.npc_id for doc in selected[:2]} == {"RIN", "MIKI"}
    assert '"scope":"last_learned"' in block
    assert '"recorded_at":"2026-01-02"' in block
    assert len(block) <= MAX_RECALL_CHARS
    assert old in documents


def test_core_size_does_not_grow_with_archive_and_respects_audience():
    documents = [
        fact(str(i), "RIN", "boundary", "Updated boundary " + str(i), f"2026-{i:05}")
        for i in range(1000)
    ]
    documents.append(fact("miki", "MIKI", "promise", "Return the key", "2026-01-01"))
    core = working_memory(documents, {"RIN", "MIKI"})
    assert len(core) == 2
    block, selected = project(documents, core_documents=core, npc_ids={"MIKI"})
    assert all(doc.npc_id == "MIKI" for doc in selected)
    assert len(block) <= MAX_RECALL_CHARS


def test_no_lexical_match_keeps_notes_and_chronicle_available():
    notes = document("notes", layer="session_note", npc_id=None, text="An important agreement")
    chronicle = document(
        "chronicle", layer="chronicle_summary", npc_id=None, text="The earlier story"
    )
    assert context_fallback([notes, chronicle, document()]) == [notes, chronicle]


async def test_chronicle_progresses_before_unavailable_embedder(monkeypatch):
    user = SimpleNamespace(llm_settings={"memory_rag": {"enabled": True}})
    monkeypatch.setattr(worker, "_load", AsyncMock(return_value=(user, object(), [])))
    summarize = AsyncMock(return_value=True)
    embed = AsyncMock(side_effect=RuntimeError("offline"))
    monkeypatch.setattr(worker, "_summarize", summarize)
    monkeypatch.setattr(worker, "_index_batch", embed)
    monkeypatch.setattr(worker, "_release", AsyncMock())
    claim = worker.Claim("s", "u", 0, 1, "token", None, False)
    assert await worker._step(claim)
    summarize.assert_awaited_once_with(claim, chronicle=True)
    embed.assert_not_awaited()


async def test_empty_lexical_recall_projects_canonical_notes(monkeypatch):
    note = document("note", layer="session_note", npc_id=None, text="Agreed to return tomorrow")
    manager = SimpleNamespace(
        user=SimpleNamespace(id="user"), state=SimpleNamespace(current_scene_id="HALL")
    )
    monkeypatch.setattr(retrieval, "_semantic_candidates", AsyncMock(return_value=([], None)))
    monkeypatch.setattr(retrieval, "collect_documents", AsyncMock(return_value=[note]))
    manager.db = object()
    recall = await retrieval._collect_recall(manager, "Продолжаем", set())
    block, selected = project(recall.documents)
    assert selected == [note]
    assert "return tomorrow" in block


def test_learning_progress_distinguishes_waiting_from_model_work():
    progress.set_phase("session", "message", "extracting")
    assert progress.snapshot("session", [])["phase"] == "extracting"
    progress.set_phase("session", "message", "waiting_to_save")
    assert progress.snapshot("session", [])["phase"] == "waiting_to_save"
    progress.finish("session", "wrong-message")
    assert progress.snapshot("session", [])["phase"] == "waiting_to_save"
    progress.finish("session", "message")
    assert progress.snapshot("session", [{"status": "pending"}])["phase"] == "queued"
    assert progress.snapshot("session", [{"status": "done"}])["phase"] == "up_to_date"


def test_recall_diagnostics_keep_safe_method_and_audience_only():
    result = safe_fields(
        {"retrieval_method": "sql_lexical", "audience": "vn_social", "text": "Private story"}
    )
    assert result == {"retrieval_method": "sql_lexical", "audience": "vn_social"}
    assert safe_fields({"audience": "Private story"}) == {}


@pytest.mark.parametrize("count", [1, 2, 4, 12])
def test_actual_serialized_recall_stays_bounded_with_escaped_content(count):
    documents = [
        replace(document(str(i)), npc_id=str(i), text='"\\\n' * 2000) for i in range(count)
    ]
    block, _ = project(documents, core_documents=documents)
    assert len(block) <= MAX_RECALL_CHARS


async def test_retry_timer_wakes_worker_without_a_ui_poll(monkeypatch):
    import asyncio

    from backend.engine.npc_journal import worker as journal_worker

    woke = asyncio.Event()
    calls = []

    def schedule(session_id, user_id):
        calls.append((session_id, user_id))
        woke.set()

    monkeypatch.setattr(journal_worker, "schedule", schedule)
    journal_worker._wake_later("retry-session", "owner", 0.001)
    try:
        await asyncio.wait_for(woke.wait(), 1)
        assert calls == [("retry-session", "owner")]
    finally:
        journal_worker._timers.pop("retry-session").cancel()


def test_empty_recall_preserves_legacy_npc_memory():
    from backend.engine.memory_rag.prompts import without_legacy_journal

    manager = SimpleNamespace(_memory_recall=retrieval.TurnRecall(enabled=True))
    npc = SimpleNamespace(metadata_json={"npc_journal": {"entries": [{"text": "A boundary"}]}})
    assert without_legacy_journal(manager, [npc])[0] is npc


def test_recall_bridge_preserves_diagnostics_without_story_text(monkeypatch):
    from unittest.mock import Mock

    from backend.core import llm_diagnostics

    emit = Mock()
    monkeypatch.setattr(llm_diagnostics, "emit", emit)
    llm_diagnostics.bridge_event(
        "gm.turn.memory_recall",
        {"audience": "vn_social", "retrieval_method": "hybrid", "text": "Private story"},
    )
    emit.assert_called_once_with(
        "gm.turn.memory_recall", audience="vn_social", retrieval_method="hybrid"
    )


def test_extraction_cast_has_global_budget_and_prioritizes_current_scene():
    import json

    from backend.engine.npc_journal.extract import MAX_KNOWN_CHARACTERS_CHARS, _bounded_known

    cast = [
        SimpleNamespace(
            id=str(i),
            name=f"Person {i}",
            current_scene_id="away",
            description="x" * 10000,
            metadata_json={},
        )
        for i in range(1000)
    ]
    present = SimpleNamespace(
        id="current",
        name="Мира",
        current_scene_id="room",
        description="A physician",
        metadata_json={},
    )
    known = _bounded_known(
        [*cast, present], SimpleNamespace(content="Она вернулась.", scene_id="room")
    )
    assert known[0]["npc_id"] == "current"
    assert known[0]["appearance"] == "A physician"
    assert len(json.dumps(known, ensure_ascii=False)) <= MAX_KNOWN_CHARACTERS_CHARS


def test_four_present_npcs_with_real_length_ids_share_core_budget():
    from uuid import UUID

    documents = [
        fact(
            str(UUID(int=i)),
            str(UUID(int=i)),
            "boundary_shoulder",
            "Please do not touch my shoulder.",
            "2026-10-28T17:00:00+00:00",
        )
        for i in range(1, 5)
    ]
    documents = [replace(doc, source_id=doc.npc_id + ":" + "a" * 32) for doc in documents]
    core = working_memory(documents, {doc.npc_id for doc in documents})
    block, selected = project(documents, core_documents=core)
    assert {doc.npc_id for doc in selected} == {doc.npc_id for doc in documents}
    assert block.count("Please do not touch my shoulder.") == 4
    assert len(block) <= MAX_RECALL_CHARS
