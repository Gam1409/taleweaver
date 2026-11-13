"""Authored source links inform comparison without following private targets."""

import json

from backend.engine.memory_rag import prompts
from backend.engine.world_info import projection
from backend.engine.world_info.types import EntryDraft, entry_hash
from tests.conftest import TestSessionLocal
from tests.test_memory_rag_retrieval import document
from tests.test_world_info_projection import _state, info_owner, portrait_world
from tests.test_world_info_recall import reference
from tests.world_info_projection_fixture import seed_entry

__all__ = ["info_owner", "portrait_world"]


def records(block):
    return [json.loads(line) for line in block.splitlines() if line.startswith("{")]


async def linked_documents(db, owner, *, target_audience="common_knowledge"):
    _, _, assertion = await seed_entry(
        db, owner, text="The archive keeper is alive.", audience="common_knowledge"
    )
    _, _, report = await seed_entry(
        db, owner, text="PRIVATE_TARGET_BODY: the keeper has died.", audience=target_audience
    )
    assertion.kind = "world_fact"
    report.kind = "rumor"
    assertion.relations = [
        {"kind": "contradicts", "target_id": report.id, "note": "PRIVATE_LINK_NOTE"}
    ]
    for entry in (assertion, report):
        draft = EntryDraft.model_validate(
            {key: getattr(entry, key) for key in EntryDraft.model_fields}
        )
        entry.content_hash = entry_hash(draft)
    await db.commit()
    documents = await projection.collect_documents(db, await _state(db), owner)
    by_id = {doc.source_id: doc for doc in documents}
    return [by_id[f"world_info:{entry.id}"] for entry in (assertion, report)]


async def test_selected_conflicting_sources_include_a_typed_comparison_link(info_owner):
    async with TestSessionLocal() as db:
        documents = await linked_documents(db, info_owner)
        block, selected = prompts.project(documents)
        assert selected == documents
        rows = records(block)
        assert rows[0]["relations"] == [
            {"kind": "contradicts", "target_source_id": documents[1].source_id}
        ]
        assert "is alive" in rows[0]["evidence"] and "has died" in rows[1]["evidence"]
        assert all(row["provenance"] == "authored_reference" for row in rows)
        assert "PRIVATE_LINK_NOTE" not in block
        assert "Relation labels are authored assertions, not proof or access to targets" in block


async def test_link_does_not_follow_or_expose_the_private_target_to_other_audiences(info_owner):
    async with TestSessionLocal() as db:
        public, private = await linked_documents(db, info_owner, target_audience="narrator_only")
        for audience in ("vn_continuity", "vn_social", "actor"):
            block, selected = prompts.project(
                [public, private],
                audience=audience,
                actor_id="NPC_NEW",
                actual_npc_ids={"NPC_NEW"},
            )
            assert selected == [public]
            row = records(block)[0]
            assert row["relations"] == [
                {"kind": "contradicts", "target_source_id": private.source_id}
            ]
            assert "PRIVATE_TARGET_BODY" not in block and "PRIVATE_LINK_NOTE" not in block
            assert private.source_attribution["id"] not in block
            assert "Never infer content of targets absent from recall" in block
            assert len(block) <= prompts.MAX_RECALL_CHARS == 2500


def test_relation_metadata_is_bounded_and_prioritizes_contradictions_then_support():
    links = tuple(
        [("related", "world_info:related"), ("part_of", "world_info:collection")]
        + [("supports", "world_info:support"), ("contradicts", "world_info:opposition")]
        + [("related", f"world_info:other-{index}") for index in range(8)]
    )
    item = reference(reference_relations=links)
    block, selected = prompts.project([item])
    assert selected == [item]
    row = records(block)[0]
    assert row["relations"] == [
        {"kind": "contradicts", "target_source_id": "world_info:opposition"},
        {"kind": "supports", "target_source_id": "world_info:support"},
    ]
    assert row["relations_omitted"] == 10
    assert len(block) <= prompts.MAX_RECALL_CHARS == 2500
    assert item.reference_relations == links


def test_legacy_documents_need_no_relation_metadata():
    item = document()
    block, selected = prompts.project([item])
    assert selected == [item]
    assert "relations" not in records(block)[0]
