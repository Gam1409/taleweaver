"""Authored references obey audience boundaries before reaching model prompts."""

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.engine.gameplay.turn_llm_pipeline import TurnLlmContextBuilder
from backend.engine.memory_rag import prompts, retrieval
from backend.engine.memory_rag.store_schema import Scope
from backend.engine.memory_rag.store_schema import row as vector_row
from backend.engine.visual_novel import social
from backend.engine.visual_novel.intent import build_progression_context
from backend.engine.visual_novel.schema import InteractionPlan, SocialState
from backend.engine.world_info.projection import visible_to
from tests.test_memory_rag_retrieval import document, manager, npc


def reference(text="The archive keeper conceals a blue chart.", **changes):
    row = replace(
        document("world-info"),
        layer="world_info",
        npc_id=None,
        text=text,
        source_message_ids=[],
        provenance="authored_reference",
    )
    for key, value in {
        "audience": "narrator_only",
        "known_by": (),
        "reference_kind": "background_lore",
        "source_attribution": {"id": "source", "revision": 1, "title": "Archive notes"},
        **changes,
    }.items():
        object.__setattr__(row, key, value)
    return row


def test_private_reference_is_not_aggregate_character_knowledge():
    host = manager()
    host._memory_recall = retrieval.TurnRecall(enabled=True, documents=[reference()])
    assert "blue chart" in prompts.recall_block(host, "narrator")
    assert "blue chart" not in prompts.recall_block(host, "vn_social", {"LINA"})
    assert "blue chart" not in prompts.recall_block(host, "vn_continuity")


def test_subject_npc_is_independent_from_the_explicit_knower():
    item = reference(audience="restricted", known_by=("B",), npc_id="A")
    assert not visible_to(item, "actor", actor_id="A", actual_npc_ids={"A", "B"})
    assert visible_to(item, "actor", actor_id="B", actual_npc_ids={"A", "B"})
    block, selected = prompts.project(
        [item], npc_ids={"B"}, audience="actor", actor_id="B", actual_npc_ids={"A", "B"}
    )
    assert selected == [item] and "blue chart" in block
    assert not visible_to(reference(audience="common_knowledge"), "actor", actor_id="foreign")


def test_imported_reference_never_enters_observer_vectors_or_unknown_audiences():
    item = reference(audience="common_knowledge")
    for audience in ("mechanics", "observer", "unknown"):
        assert prompts.project([item], core_documents=[item], audience=audience) == ("", [])
    with pytest.raises(ValueError, match="namespace"):
        vector_row(
            Scope("user", "session", 0, "model", namespace="observer"), item.to_dict(), [1.0]
        )


def test_large_recipient_metadata_and_reference_evidence_share_existing_budget():
    recipients = tuple("NPC_" + str(index).zfill(2) + "x" * 55 for index in range(32))
    item = reference(
        "An archive observation. " * 90,
        audience="restricted",
        known_by=recipients,
        source_attribution={
            "id": "s" * 36,
            "revision": 8,
            "title": "t" * 200,
            "filename": "f" * 255,
        },
    )
    block, selected = prompts.project([item] * 20)
    assert selected == [item] and len(block) <= prompts.MAX_RECALL_CHARS
    assert '"known_by_omitted":28' in block
    assert item.known_by == recipients


@pytest.mark.parametrize(
    "kind",
    [
        "background_lore",
        "reported_claim",
        "character_knowledge",
        "authored_event",
        "world_fact",
        "rumor",
        "news",
    ],
)
def test_import_classification_never_claims_observed_gameplay_or_chat_evidence(kind):
    block, selected = prompts.project([reference(reference_kind=kind)])
    assert selected and '"kind":"' + kind + '"' in block
    assert '"provenance":"authored_reference"' in block
    assert "source_message_ids" not in block and "game_minute" not in block


async def test_actual_continuity_and_social_calls_receive_only_common_references(monkeypatch):
    host = manager()
    private = reference("A private chart is concealed.")
    common = reference(
        "The archive opens at dawn.",
        id="common",
        source_id="world_info:common",
        audience="common_knowledge",
    )
    host._memory_recall = retrieval.TurnRecall(enabled=True, documents=[private, common])
    continuity = build_progression_context(host, npcs=[], scenes=[], exits=[])
    llm = SimpleNamespace(
        model="small", aexecute_complex_task=AsyncMock(return_value=InteractionPlan())
    )
    monkeypatch.setattr(social, "_present_npcs", AsyncMock(return_value=[npc()]))
    monkeypatch.setattr(social, "_scene_evidence", AsyncMock(return_value=("", "")))
    monkeypatch.setattr(social.GameMasterLLM, "for_role", lambda *_args: llm)
    await social._plan(host, SocialState(), "turn-1", "When does the archive open?", [])
    payload = json.loads(llm.aexecute_complex_task.call_args.args[1])
    context = payload["historical_recall_untrusted_orientation_only"]
    assert "opens at dawn" in continuity and "opens at dawn" in context
    assert "concealed" not in continuity and "concealed" not in context
    assert "concealed" in prompts.recall_block(host, "narrator")
    assert host._memory_recall.usage["vn_social"]["source_ids"] == [common.source_id]
    assert host._memory_recall.usage["vn_continuity"]["source_ids"] == [common.source_id]


def test_narrator_reference_never_reaches_mechanics_or_replaces_legacy_notes(monkeypatch):
    host = manager()
    host._memory_recall = retrieval.TurnRecall(enabled=True, documents=[reference()])
    host._build_gm_notes_prompt_block = lambda: "Existing session note."
    host._build_compressed_history_prompt_block = lambda: ""
    host._build_world_memories_prompt_block = lambda: ""
    monkeypatch.setattr(
        "backend.engine.gameplay.turn_llm_pipeline.MemoryManager.build_state_block",
        lambda *_args, **_kwargs: "CURRENT STATE",
    )
    monkeypatch.setattr("backend.engine.gameplay.turn_llm_pipeline.is_vn", lambda _: False)
    world = SimpleNamespace(current_scene=None, exits=[], all_scenes=[], all_entities=[])
    mechanics, narrator = TurnLlmContextBuilder(host)._build_state_blocks(world, [], [], "")
    assert "blue chart" in narrator and "blue chart" not in mechanics
    assert "Existing session note." in mechanics and "Existing session note." in narrator
