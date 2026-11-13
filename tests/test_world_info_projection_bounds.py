"""Recipient verification reads only IDs referenced by the bounded selected records."""

import json
from copy import deepcopy
from datetime import datetime, timedelta
from uuid import uuid4

from backend.engine.memory_rag.ranking import rank_documents
from backend.engine.world_info import projection
from backend.engine.world_info.types import EntryDraft, entry_hash, searchable_text
from backend.models.world_entity import WorldEntity
from backend.models.world_info import WorldInfoEntry
from tests.conftest import TestSessionLocal
from tests.test_world_info_projection import _state, info_owner, portrait_world
from tests.world_info_projection_fixture import seed_entry

__all__ = ["info_owner", "portrait_world"]


async def test_group_only_query_survives_canonical_loading_and_host_ranking(info_owner):
    async with TestSessionLocal() as db:
        _, _, entry = await seed_entry(db, info_owner)
        values = {key: getattr(entry, key) for key in EntryDraft.model_fields}
        draft = EntryDraft.model_validate(values | {"group_name": "Winter chronicle"})
        entry.group_name = draft.group_name
        entry.search_text = searchable_text(draft)
        entry.content_hash = entry_hash(draft)
        await db.commit()
        documents = await projection.collect_documents(
            db, await _state(db), info_owner, query="Winter chronicle"
        )
        assert len(documents) == 1
        ranked = rank_documents(documents, "Winter chronicle", set(), "TOWER")
        assert ranked == documents
        assert "Winter chronicle" in documents[0].text
        assert documents[0].provenance == "authored_reference"


async def test_unrelated_session_npcs_do_not_expand_recipient_materialization(
    info_owner, monkeypatch
):
    async with TestSessionLocal() as db:
        await seed_entry(db, info_owner, audience="restricted", known_by=["NPC_NEW"])
        db.add_all(
            [
                WorldEntity(
                    id=f"UNRELATED_{index}",
                    session_id="portrait-session",
                    entity_type="NPC",
                    name="Other character",
                    description="An unrelated session character.",
                    current_scene_id="TOWER",
                )
                for index in range(100)
            ]
        )
        await db.commit()
        state = await _state(db)
        scalars = db.scalars
        checked = []

        async def bounded(statement, *args, **kwargs):
            compiled = statement.compile()
            assert "world_entities.id IN (SELECT" in str(compiled)
            assert json.dumps(["NPC_NEW"]) in compiled.params.values()
            rows = await scalars(statement, *args, **kwargs)
            values = list(rows)
            checked.append(values)
            return values

        monkeypatch.setattr(db, "scalars", bounded)
        for query in (None, "archive"):
            documents = await projection.collect_documents(db, state, info_owner, query=query)
            assert len(documents) == 1 and documents[0].unresolved_known_by == ()
        assert checked == [["NPC_NEW"], ["NPC_NEW"]]


async def test_foreground_combines_at_most_eighty_fresh_lexical_and_semantic_rows(info_owner):
    async with TestSessionLocal() as db:
        source, revision, original = await seed_entry(db, info_owner)
        semantic_ids = []
        for index in range(96):
            facts = deepcopy(original.facts)
            facts[0]["id"] = str(uuid4())
            title = f"Aquamarine treaty {index}" if 32 <= index < 64 else f"Record {index}"
            draft = EntryDraft(id=str(uuid4()), title=title, facts=facts)
            if index < 32:
                semantic_ids.append(draft.id)
            db.add(
                WorldInfoEntry(
                    id=draft.id,
                    user_id=info_owner,
                    session_id=source.session_id,
                    source_id=source.id,
                    source_revision_id=revision.id,
                    batch_index=1 + index // 4,
                    ordinal=index % 4,
                    title=draft.title,
                    summary="",
                    facts=[fact.model_dump() for fact in draft.facts],
                    tags=[],
                    relations=[],
                    kind=draft.kind,
                    audience="narrator_only",
                    known_by=[],
                    status="published",
                    search_text=searchable_text(draft),
                    content_hash=entry_hash(draft),
                    updated_at=datetime(2026, 1, 1) + timedelta(minutes=index),
                )
            )
        await db.commit()
        candidates = [
            {"source_id": f"world_info:{identifier}", "layer": "world_info"}
            for identifier in semantic_ids
        ]
        # Even a caller supplying a much larger cache cannot expand the SQL ID set.
        candidates += candidates * 312
        result = await projection.collect_documents(
            db, await _state(db), info_owner, query="aquamarine", candidates=candidates
        )
        assert len(result) == 80
        assert set(semantic_ids) <= {row.source_id.partition(":")[2] for row in result}
        assert sum("Aquamarine" in row.text for row in result) == 32
