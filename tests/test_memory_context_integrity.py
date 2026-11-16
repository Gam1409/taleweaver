"""Retrieved episodes retain their identity and relevant evidence in the final prompt."""

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.engine.memory_rag import prompts, retrieval
from backend.engine.memory_rag.core import working_memory
from tests.test_memory_rag_retrieval import document, manager, npc


def records(block):
    return [json.loads(line) for line in block.splitlines() if line.startswith("{")]


def test_relevant_tail_is_an_exact_excerpt_in_the_published_context():
    fact = "The collected sample is in the blue vial."
    item = document("message", layer="dialogue", npc_id=None, text="Routine detail. " * 90 + fact)
    block, selected = prompts.project([item], query="Where is the collected sample?")
    assert selected == [item] and fact in block
    entry = records(block)[0]
    start, end = entry["document_span"]
    assert entry["evidence"] == item.text[start:end]
    assert len(block) <= prompts.MAX_RECALL_CHARS


def test_repeated_words_in_distinct_locations_remain_distinct_events():
    first = document(
        "m1",
        layer="dialogue",
        npc_id=None,
        scene_id="CLINIC",
        text="Rin handed the brass key to Mira.",
    )
    second = replace(
        first,
        id="m2",
        source_id="m2",
        source_message_ids=["m2"],
        scene_id="EMBASSY",
        created_at="2026-11-07",
    )
    block, selected = prompts.project([first, second, first])
    assert selected == [first, second]
    assert {r["scene_id"] for r in records(block)} == {"CLINIC", "EMBASSY"}
    assert {tuple(r["source_message_ids"]) for r in records(block)} == {("m1",), ("m2",)}


@pytest.mark.parametrize("count", [6, 12, 20])
def test_large_cast_keeps_useful_working_memory_with_the_same_global_cap(count):
    items = [
        document(
            f"fact-{i}",
            npc_id=f"NPC-{i}",
            topic="promise",
            text=f"NPC-{i} promised to return sample {i}.",
        )
        for i in range(count)
    ]
    core = working_memory(items, {d.npc_id for d in items})
    block, selected = prompts.project(items, core_documents=core)
    assert selected and block
    assert len({d.npc_id for d in selected}) >= 3
    assert len(block) <= prompts.MAX_RECALL_CHARS


def test_unrepresentable_recall_cannot_silently_remove_the_legacy_journal():
    item = document("x" * 3000)
    host = SimpleNamespace(_memory_recall=retrieval.TurnRecall(enabled=True, documents=[item]))
    actor = npc()
    actor.metadata_json = {"npc_journal": {"entries": ["original"]}}
    assert not prompts.project([item])[0]
    assert not prompts.recall_enabled(host)
    assert prompts.without_legacy_journal(host, [actor]) == [actor]


async def test_scene_rebuild_refreshes_cast_and_ranking_without_a_second_vector_request(
    monkeypatch,
):
    host = manager()
    other = SimpleNamespace(entity_type="NPC", id="KING", name="King")
    collect = AsyncMock(return_value=[document()])
    semantic = AsyncMock(return_value=([], None))
    monkeypatch.setattr(retrieval, "collect_documents", collect)
    monkeypatch.setattr(retrieval, "_semantic_candidates", semantic)
    first = await retrieval.prepare_recall(host, "Enter the embassy", [npc()])
    host.state.current_scene_id = "EMBASSY"
    second = await retrieval.prepare_recall(host, "Enter the embassy", [other])
    assert first is not second
    assert collect.await_count == 2
    assert collect.call_args.kwargs["npc_ids"] == {"KING"}
    assert semantic.await_count == 1
