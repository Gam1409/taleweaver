"""Rare authored terms survive broad context expansion within the recall bounds."""

from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from backend.engine.memory_rag import prompts, retrieval
from backend.engine.world_info import projection
from backend.engine.world_info.types import EntryDraft, entry_hash, searchable_text
from backend.models.memory_rag import MemoryIndexState
from backend.models.user import User
from backend.models.world_info import WorldInfoEntry
from tests.conftest import TestSessionLocal
from tests.test_world_info_projection import _state, info_owner, portrait_world
from tests.world_info_projection_fixture import seed_entry

__all__ = ["info_owner", "portrait_world"]


async def catalog(db, owner, *, target_has_context=False, semantic=0, recent=0):
    source, revision, target = await seed_entry(db, owner, text="A catalogued document.")
    title = "Aquamarine archive treaty" if target_has_context else "Aquamarine treaty"
    draft = EntryDraft.model_validate(
        {key: getattr(target, key) for key in EntryDraft.model_fields}
        | {"title": title, "tags": []}
    )
    target.title = draft.title
    target.tags = []
    target.search_text = searchable_text(draft)
    target.content_hash = entry_hash(draft)
    target.updated_at = datetime(2026, 1, 1)
    semantic_ids = []
    titles = (
        [f"Archive record {index}" for index in range(40)]
        + [f"Semantic record {index}" for index in range(semantic)]
        + [f"Fresh record {index}" for index in range(recent)]
    )
    for index, title in enumerate(titles):
        facts = deepcopy(target.facts)
        facts[0]["id"] = str(uuid4())
        entry = EntryDraft(id=str(uuid4()), title=title, facts=facts)
        if title.startswith("Semantic"):
            semantic_ids.append(entry.id)
        db.add(
            WorldInfoEntry(
                id=entry.id,
                user_id=owner,
                session_id=source.session_id,
                source_id=source.id,
                source_revision_id=revision.id,
                batch_index=1 + index // 4,
                ordinal=index % 4,
                status="published",
                search_text=searchable_text(entry),
                content_hash=entry_hash(entry),
                updated_at=datetime(2026, 2, 1) + timedelta(minutes=index),
                **entry.model_dump(exclude={"id"}),
            )
        )
    await db.commit()
    return target.id, semantic_ids


@pytest.mark.parametrize("mode", ["paused", "unavailable"])
@pytest.mark.parametrize("target_has_context", [False, True])
async def test_rare_reference_survives_scene_name_expansion_without_vectors(
    info_owner, monkeypatch, mode, target_has_context
):
    embed = AsyncMock(side_effect=RuntimeError("Mock embedding service unavailable"))
    monkeypatch.setattr(retrieval, "embed_texts", embed)
    async with TestSessionLocal() as db:
        target_id, _ = await catalog(db, info_owner, target_has_context=target_has_context)
        state = await _state(db)
        user = await db.get(User, info_owner)
        user.llm_settings = {"memory_rag": {"enabled": True, "model": "mock-embed"}}
        db.add(
            MemoryIndexState(
                session_id=state.session_id,
                user_id=info_owner,
                template_id=state.template_id,
                paused=mode == "paused",
                signature="mock-signature",
                indexed_revision=1,
            )
        )
        await db.commit()
        host = SimpleNamespace(db=db, user=user, state=state)
        npc = SimpleNamespace(id="NPC_NEW", name="Archive", entity_type="NPC")
        recall = await retrieval.prepare_recall(host, "aquamarine", [npc])
        assert recall.enabled and recall.method == "sql_lexical"
        assert "Present characters: Archive" in recall.query
        assert f"world_info:{target_id}" in {document.source_id for document in recall.documents}
        block, selected = prompts.project(recall.documents, query=recall.query)
        assert any(document.source_id == f"world_info:{target_id}" for document in selected)
        assert "Aquamarine" in block and len(block) <= prompts.MAX_RECALL_CHARS
        assert embed.await_count == (mode == "unavailable")


async def test_per_term_candidates_share_the_existing_lexical_and_total_limits(info_owner):
    async with TestSessionLocal() as db:
        target_id, semantic_ids = await catalog(db, info_owner, semantic=32, recent=16)
        candidates = [
            {"source_id": f"world_info:{identifier}", "layer": "world_info"}
            for identifier in semantic_ids
        ]
        result = await projection.collect_documents(
            db,
            await _state(db),
            info_owner,
            query="aquamarine archive",
            candidates=candidates,
        )
        identifiers = {document.source_id for document in result}
        assert len(result) == 80
        assert f"world_info:{target_id}" in identifiers
        assert {f"world_info:{identifier}" for identifier in semantic_ids} <= identifiers
        assert sum("Fresh record" in document.text for document in result) == 16
        assert (
            sum(
                "Archive record" in document.text or "Aquamarine" in document.text
                for document in result
            )
            == projection.LEXICAL_ENTRIES
        )
