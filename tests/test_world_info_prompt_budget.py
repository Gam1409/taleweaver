"""Optional prompt metadata cannot displace accepted reference evidence."""

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.memory_rag import prompts, retrieval
from backend.engine.world_info import projection
from backend.engine.world_info.types import EntryDraft, entry_hash, searchable_text
from backend.models.user import User
from tests.conftest import TestSessionLocal
from tests.test_memory_rag_retrieval import document
from tests.test_vn_turn_integration import TurnRoles, install_roles, seed_vn
from tests.test_world_info_projection import _state, info_owner, portrait_world
from tests.test_world_info_recall import reference
from tests.world_info_projection_fixture import seed_entry

__all__ = ["info_owner", "portrait_world"]


def records(block):
    return [json.loads(line) for line in block.splitlines() if line.startswith("{")]


def recipients():
    return tuple("NPC_" + str(index).zfill(2) + "x" * 94 for index in range(32))


def large_reference(*, text="Sapphire archive doors open at dawn.", escaped=False):
    labels = {"title": "T" * 200, "filename": "F" * 252 + ".md"}
    if escaped:
        labels = {"title": '"' * 200, "filename": "\\" * 252 + ".md"}
    return reference(
        text,
        source_id="world_info:" + str(uuid4()),
        audience="restricted",
        known_by=recipients(),
        unresolved_known_by=recipients(),
        source_attribution={"id": str(uuid4()), "revision": 8, **labels},
        reference_relations=tuple(("contradicts", "world_info:" + str(uuid4())) for _ in range(12)),
    )


async def seed_large_reference(db, owner, sid="portrait-session"):
    source, revision, entry = await seed_entry(
        db,
        owner,
        sid=sid,
        text="Sapphire archive doors open at dawn.",
        audience="restricted",
        known_by=recipients(),
    )
    _, _, target = await seed_entry(db, owner, sid=sid, text="A caravan travels west.")
    source.title = "T" * 200
    source.filename = revision.filename = "F" * 252 + ".md"
    entry.unresolved_known_by = list(recipients())
    entry.relations = [{"target_id": target.id, "kind": "related", "note": ""}]
    draft = EntryDraft.model_validate({key: getattr(entry, key) for key in EntryDraft.model_fields})
    entry.content_hash = entry_hash(draft)
    entry.search_text = searchable_text(draft)
    await db.commit()
    return source, entry


async def test_sql_ranked_reference_survives_combined_labels_dormant_scope_and_link(info_owner):
    async with TestSessionLocal() as db:
        source, entry = await seed_large_reference(db, info_owner)
        user = await db.get(User, info_owner)
        user.llm_settings = {"memory_rag": {"enabled": True}}
        await db.commit()
        state = await _state(db)
        canonical = await projection.collect_documents(db, state, info_owner, query="sapphire")
        expected = next(row for row in canonical if row.source_id == "world_info:" + entry.id)
        host = SimpleNamespace(db=db, user=user, state=state)
        recall = await retrieval.prepare_recall(host, "sapphire", [])
        assert expected in recall.documents
        block = prompts.recall_block(host, "narrator")
        row = next(row for row in records(block) if row["source_id"] == expected.source_id)
        assert "Sapphire archive doors open at dawn." in row["evidence"]
        assert row["source"]["id"] == source.id and row["source"]["revision"] == 1
        assert expected.known_by == expected.unresolved_known_by == recipients()
        assert entry.known_by == entry.unresolved_known_by == list(recipients())
        assert row["unresolved_known_by_count"] == 32
        assert not row.get("known_by")
        assert len(block) <= 2500
        assert prompts.recall_block(host, "mechanics") == ""


@pytest.mark.parametrize("escaped", [False, True])
@pytest.mark.parametrize("dormant", [False, True])
def test_maximum_metadata_preserves_useful_exact_evidence_and_citations(escaped, dormant):
    text = ('Archive "quoted" note.\\\n' if escaped else "Sapphire archive observation. ") * 30
    item = large_reference(text=text, escaped=escaped)
    if not dormant:
        item = replace(item, unresolved_known_by=())
    block, selected = prompts.project([item], query="archive")
    assert selected == [item]
    row = records(block)[0]
    assert len(row["evidence"]) >= 160
    start, end = row["document_span"]
    assert row["evidence"] == item.text[start:end]
    assert row["source"]["id"] == item.source_attribution["id"]
    assert row["source"]["revision"] == 8
    assert row["source"]["title_omitted"] > 0 and row["source"]["filename_omitted"] > 0
    if dormant:
        assert row["unresolved_known_by_count"] == 32
        assert not row.get("known_by")
    else:
        assert row["known_by_count"] == 32
        assert not row.get("unresolved_known_by")
    assert row["relations_omitted"] >= 10
    assert row["provenance"] == "authored_reference" and row["audience"] == "restricted"
    assert "Omitted recipients confer no knowledge" in block
    assert len(block) <= prompts.MAX_RECALL_CHARS == 2500
    assert len(item.known_by) == 32
    assert len(item.unresolved_known_by) == (32 if dormant else 0)
    assert len(item.reference_relations) == 12
    assert len(item.source_attribution["title"]) == 200
    assert len(item.source_attribution["filename"]) == 255


def test_reference_scope_previews_never_duplicate_dormant_recipient_ids():
    item = replace(large_reference(), unresolved_known_by=recipients()[1:])
    block, selected = prompts.project([item])
    assert selected == [item]
    row = records(block)[0]
    assert row["known_by_count"] == 1 and row["unresolved_known_by_count"] == 31
    assert not set(row.get("known_by", [])) & set(row.get("unresolved_known_by", []))
    assert all(identifier not in item.unresolved_known_by for identifier in row.get("known_by", []))
    assert all(
        identifier in item.unresolved_known_by for identifier in row.get("unresolved_known_by", [])
    )
    assert item.known_by == recipients()


def test_escaped_legacy_evidence_uses_available_space_with_exact_span():
    item = document("quoted-dialogue", layer="dialogue", text='"' * 600)
    encoded = prompts._record(item, 650)
    row = json.loads(encoded)
    assert len(row["evidence"]) >= 160
    start, end = row["document_span"]
    assert row["evidence"] == item.text[start:end]
    assert row["source_message_ids"] == item.source_message_ids
    assert row["provenance"] == item.provenance
    assert len(encoded) <= 650


@pytest.mark.parametrize("available", range(240, 321, 2))
def test_escaped_excerpt_is_skipped_when_less_than_forty_characters_fit(available):
    item = document(
        "x",
        layer="dialogue",
        npc_id=None,
        scene_id=None,
        text='"' * 600,
        provenance="observed",
        source_message_ids=["x"],
        created_at="2026-01-01",
    )
    encoded = prompts._record(item, available)
    assert not encoded or len(json.loads(encoded)["evidence"]) >= 40
    assert len(encoded) <= available


def test_mixed_reference_core_summary_and_dialogue_share_one_budget():
    core = document(text="Lina prefers tea.")
    summary = document(
        "summary",
        layer="story_summary",
        npc_id=None,
        text="An earlier archive visit.",
        provenance="summary",
    )
    dialogue = document(
        "dialogue",
        layer="dialogue",
        npc_id=None,
        text="The keeper greeted the visitors.",
        provenance="observed",
    )
    item = large_reference()
    block, selected = prompts.project([item, summary, dialogue], core_documents=[core])
    assert selected == [core, item, summary, dialogue]
    rows = records(block)
    assert [row["provenance"] for row in rows] == [
        "claimed",
        "authored_reference",
        "summary",
        "observed",
    ]
    assert rows[0]["scope"] == "last_learned"
    assert all(row["evidence"] for row in rows)
    assert len(block) <= 2500


async def test_real_turn_uses_sql_reference_with_large_metadata_without_extra_requests(monkeypatch):
    roles = TurnRoles()
    install_roles(monkeypatch, roles)
    embed = AsyncMock(side_effect=AssertionError("No extra embedding request"))
    monkeypatch.setattr(retrieval, "embed_texts", embed)
    async with TestSessionLocal() as db:
        user, _, state, _ = await seed_vn(db)
        await seed_large_reference(db, user.id, state.session_id)
        user.llm_settings = {"memory_rag": {"enabled": True}}
        await db.commit()
        host = GameTurnManager(db, state.session_id, user)
        events = [event async for event in host.process_turn("Tell me about the sapphire archive.")]
        assert not any(event.startswith("event: error") for event in events), "".join(events)
        assert any(event.startswith("event: final") for event in events)
        assert len(roles.prompts) == 1
        narrator = roles.prompts[0][1]["messages"][-1]["content"]
        assert "Sapphire archive doors open at dawn." in narrator
        assert "Sapphire archive doors open at dawn." not in str(roles.calls[:2])
        assert len(prompts.recall_block(host, "narrator")) <= 2500
        assert [call[0] for call in roles.calls] == [
            "VNProgressionIntent",
            "InteractionPlan",
            "SharedItemExtraction",
        ]
        embed.assert_not_awaited()
