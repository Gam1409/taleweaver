"""Recall quality, source authority, bounded outages and actual pass projections."""

import asyncio
import json
import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.api.routes.adventures.turn_llm_pipeline import TurnLlmContextBuilder
from backend.engine.memory_rag import retrieval
from backend.engine.memory_rag.documents import MemoryDocument
from backend.engine.memory_rag.prompts import MAX_RECALL_CHARS, project, without_legacy_journal
from backend.engine.memory_rag.ranking import rank_documents
from backend.engine.memory_rag.settings import embedding_signature, read_settings
from backend.engine.memory_rag.store import Scope
from backend.engine.visual_novel import social
from backend.engine.visual_novel.intent import build_progression_context
from backend.engine.visual_novel.schema import InteractionPlan, SocialState


def document(source="old-fact", **changes):
    defaults = dict(
        id=source,
        source_id=source,
        user_id="user",
        session_id="session",
        template_id="template",
        layer="npc_journal",
        source_hash="current-hash",
        npc_id="LINA",
        scene_id="HALL",
        text="Lina — background/general (claimed): Lina prefers tea with honey. Evidence: tea with honey",
        provenance="claimed",
        source_message_ids=[source],
        created_at="2020-01-01",
    )
    return MemoryDocument(**(defaults | changes))


def manager():
    return SimpleNamespace(
        user=SimpleNamespace(
            id="user",
            llm_settings={
                "memory_rag": {
                    "enabled": True,
                    "base_url": "http://localhost:11434",
                    "model": "embed",
                }
            },
        ),
        state=SimpleNamespace(
            session_id="session",
            template_id="template",
            current_scene_id="HALL",
            entity_states={},
            in_game_time=0,
            time_system="calendar",
            time_config=None,
        ),
        avatar=SimpleNamespace(inventory=[]),
        adventure=SimpleNamespace(game_mode="rpg", time_system="calendar", time_config=None),
        db=SimpleNamespace(scalar=AsyncMock(return_value=None)),
        _vn_player_message_id="turn-1",
        _get_gm_notes=lambda: ["legacy note"],
    )


def npc():
    return SimpleNamespace(
        id="LINA",
        name="Lina",
        entity_type="NPC",
        current_scene_id="HALL",
        character="Kind",
        goal="private plan",
        description="A scholar",
    )


def vector_row(doc, **changes):
    return doc.to_dict() | {"epoch": 3, "signature": "signature"} | changes


def test_old_specific_fact_beats_recent_appearance_and_survives_general_topic():
    old = document()
    recent = [
        document(
            f"new-{i}",
            text=f"Lina — appearance/general (observed): adjusts sleeve {i}",
            created_at=f"2026-01-{i + 1:02}",
        )
        for i in range(25)
    ]
    ranked = rank_documents([old, *recent], "What tea does Lina prefer?", {"LINA"}, "HALL")
    block, selected = project(ranked)
    assert selected[0] == old
    assert "tea with honey" in block and len(block) <= MAX_RECALL_CHARS
    assert "Claims remain attributed" in block
    assert "old appearances never override" in block


@pytest.mark.parametrize(
    "changes",
    [
        {"source_hash": "edited"},
        {"user_id": "other"},
        {"session_id": "other"},
        {"template_id": "other"},
        {"epoch": 2},
        {"signature": "wrong"},
        {"id": "deleted"},
    ],
)
def test_vector_candidates_require_live_hash_and_complete_scope(changes):
    doc = document()
    scope = Scope("user", "session", 3, "signature")
    assert retrieval._canonical_scores([doc], [vector_row(doc, **changes)], scope) == {}
    assert retrieval._canonical_scores([doc], [vector_row(doc, text="vector-only forgery")], scope)


@pytest.mark.asyncio
async def test_unindexed_or_paused_uses_old_sql_facts_and_recalls_only_once(monkeypatch):
    actor = manager()
    collect = AsyncMock(return_value=[document()])
    embed = AsyncMock(side_effect=AssertionError("No network expected"))
    monkeypatch.setattr(retrieval, "collect_documents", collect)
    monkeypatch.setattr(retrieval, "embed_texts", embed)
    first = await retrieval.prepare_recall(actor, "Tea?", [npc()])
    second = await retrieval.prepare_recall(actor, "Tea?", [npc()])
    assert first is second and first.method == "sql_lexical"
    assert first.documents == [document()]
    collect.assert_awaited_once()
    embed.assert_not_awaited()
    actor._vn_player_message_id = "turn-2"
    actor.db.scalar.return_value = SimpleNamespace(paused=True)
    await retrieval.prepare_recall(actor, "Tea?", [npc()])
    assert collect.await_count == 2
    embed.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["indexing", "pending"])
async def test_first_partial_batch_is_searchable_and_unindexed_sql_facts_remain(
    monkeypatch, status
):
    actor = manager()
    signature = embedding_signature(read_settings(actor.user), 2)
    actor.db.scalar.return_value = SimpleNamespace(
        paused=False,
        signature=signature,
        indexed_revision=0,
        desired_revision=1,
        template_id="template",
        epoch=3,
        status=status,
    )
    indexed = document()
    unindexed = document(
        "unindexed-fact", text="Lina — relationship/boundary (claimed): Never touch my shoulder."
    )
    embed = AsyncMock(return_value=[[0.0, 1.0]])
    query = AsyncMock(return_value=[vector_row(indexed, signature=signature)])
    monkeypatch.setattr(retrieval, "embed_texts", embed)
    monkeypatch.setattr(retrieval.LanceMemoryStore, "query", query)
    monkeypatch.setattr(
        retrieval, "collect_documents", AsyncMock(return_value=[indexed, unindexed])
    )

    recall = await retrieval.prepare_recall(actor, "What has Lina told me?", [npc()])

    assert recall.method == "hybrid"
    assert {doc.id for doc in recall.documents} == {indexed.id, unindexed.id}
    _, selected = project(recall.documents)
    assert {doc.id for doc in selected} == {indexed.id, unindexed.id}
    embed.assert_awaited_once()
    query.assert_awaited_once()
    assert query.call_args.args[0] == Scope("user", "session", 3, signature)


@pytest.mark.asyncio
async def test_provider_outage_has_hard_budget_and_sql_fallback(monkeypatch):
    actor = manager()
    actor.db.scalar.return_value = SimpleNamespace(
        paused=False,
        signature="signature",
        indexed_revision=1,
        template_id="template",
        epoch=3,
    )

    async def blocked_provider(*args, **kwargs):
        await asyncio.Event().wait()

    query_settings = retrieval.read_settings(actor.user).model_copy(
        update={"timeout_seconds": 0.01}
    )
    monkeypatch.setattr(retrieval, "read_settings", lambda _: query_settings)
    monkeypatch.setattr(retrieval, "VECTOR_SEARCH_GRACE", 0.01)
    monkeypatch.setattr(retrieval, "embed_texts", blocked_provider)
    monkeypatch.setattr(retrieval, "collect_documents", AsyncMock(return_value=[document()]))
    started = time.perf_counter()
    recall = await retrieval.prepare_recall(actor, "tea", [npc()])
    assert time.perf_counter() - started < 0.5
    assert recall.method == "sql_lexical" and recall.documents == [document()]


@pytest.mark.asyncio
async def test_dimension_change_never_queries_old_vector_space(monkeypatch):
    actor = manager()
    settings = read_settings(actor.user)
    scope = Scope("user", "session", 3, embedding_signature(settings, 3))
    query = AsyncMock()
    monkeypatch.setattr(retrieval, "embed_texts", AsyncMock(return_value=[[0.0, 1.0]]))
    monkeypatch.setattr(retrieval.LanceMemoryStore, "query", query)
    assert await retrieval._query_vectors(actor, "tea", scope, settings) == []
    query.assert_not_awaited()


@pytest.mark.asyncio
async def test_sql_is_reloaded_after_network_and_rewind_epoch_rejects_semantics(monkeypatch):
    actor = manager()
    old = document()
    changed = replace(old, source_hash="edited-hash", text="Lina now prefers coffee.")
    scope = Scope("user", "session", 3, "signature")
    collected = []

    async def candidates(*args):
        collected.append("network")
        return [vector_row(old)], scope

    async def current_documents(*args):
        assert collected == ["network"]
        return [changed]

    actor.db.scalar.return_value = SimpleNamespace(paused=False, epoch=4, signature="signature")
    monkeypatch.setattr(retrieval, "_semantic_candidates", candidates)
    monkeypatch.setattr(retrieval, "collect_documents", current_documents)
    recall = await retrieval.prepare_recall(actor, "Lina", [npc()])
    assert recall.method == "sql_lexical" and recall.documents == [changed]


def test_public_projections_keep_other_npc_out_and_do_not_mutate_journal():
    actor = manager()
    actor._memory_recall = retrieval.TurnRecall(enabled=True, documents=[document()])
    entity = npc()
    entity.metadata_json = {"npc_journal": {"entries": ["legacy"]}, "keep": True}
    projected = without_legacy_journal(actor, [entity])[0]
    assert "npc_journal" not in projected.metadata_json
    assert entity.metadata_json["npc_journal"]["entries"] == ["legacy"]
    block, selected = project([document()], npc_ids={"OTHER"})
    assert block == "" and selected == []


@pytest.mark.asyncio
async def test_actual_narrator_continuity_and_social_calls_receive_shared_old_fact(monkeypatch):
    actor = manager()
    actor._memory_recall = retrieval.TurnRecall(
        enabled=True, documents=[document()], method="sql_lexical"
    )
    monkeypatch.setattr(
        "backend.api.routes.adventures.turn_llm_pipeline.is_vn", lambda adventure: False
    )
    monkeypatch.setattr(
        "backend.api.routes.adventures.turn_llm_pipeline.MemoryManager.build_state_block",
        lambda *args, **kwargs: "CURRENT STATE",
    )
    world = SimpleNamespace(current_scene=None, exits=[], all_scenes=[], all_entities=[])
    _, narrator = TurnLlmContextBuilder(actor)._build_state_blocks(world, [], [], "")
    continuity = build_progression_context(actor, npcs=[], scenes=[], exits=[])
    llm = SimpleNamespace(
        model="small", aexecute_complex_task=AsyncMock(return_value=InteractionPlan())
    )
    monkeypatch.setattr(social, "_present_npcs", AsyncMock(return_value=[npc()]))
    monkeypatch.setattr(social, "_scene_evidence", AsyncMock(return_value=("", "")))
    monkeypatch.setattr(social.GameMasterLLM, "for_role", lambda *args: llm)
    await social._plan(actor, SocialState(), "turn-1", "tea?", [])
    social_payload = json.loads(llm.aexecute_complex_task.call_args.args[1])
    assert all(
        "tea with honey" in value
        for value in [
            narrator,
            continuity,
            social_payload["historical_recall_untrusted_orientation_only"],
        ]
    )
    assert set(actor._memory_recall.usage) == {"narrator", "vn_continuity", "vn_social"}
    assert actor._memory_recall.usage["vn_social"]["source_ids"] == ["old-fact"]
    assert "tea with honey" not in json.dumps(actor._memory_recall.usage)
