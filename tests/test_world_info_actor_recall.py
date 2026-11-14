"""Real SQL and Lance candidate bounds apply only after actor access checks."""

from copy import deepcopy
from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from backend.engine.memory_rag.documents import MemoryDocument
from backend.engine.memory_rag.prompts import project
from backend.engine.memory_rag.store import LanceMemoryStore, Scope
from backend.engine.world_info import projection
from backend.models.world_info import WorldInfoEntry
from tests.conftest import TestSessionLocal
from tests.test_world_info_projection import _state, info_owner, portrait_world
from tests.world_info_projection_fixture import seed_entry

__all__ = ["info_owner", "portrait_world"]


async def test_inaccessible_sql_candidates_cannot_starve_accessible_old_reference(info_owner):
    async with TestSessionLocal() as db:
        _, _, old = await seed_entry(db, info_owner, audience="restricted", known_by=["NPC_NEW"])
        old.updated_at = datetime(2020, 1, 1)
        for index in range(96):
            fields = {
                column.key: deepcopy(getattr(old, column.key))
                for column in WorldInfoEntry.__table__.columns
                if column.key not in {"id", "created_at", "updated_at"}
            }
            fields.update(
                batch_index=index + 1,
                audience="narrator_only" if index % 2 else "restricted",
                known_by=[] if index % 2 else ["OTHER"],
                updated_at=datetime(2026, 1, 1) + timedelta(minutes=index),
            )
            db.add(WorldInfoEntry(id=str(uuid4()), **fields))
        await db.commit()
        state = await _state(db)
        for query in ("unmatched", "archive"):
            selected = await projection.collect_documents(
                db, state, info_owner, actor_id="NPC_NEW", query=query
            )
            assert [doc.source_id for doc in selected] == ["world_info:" + old.id]
        assert await projection.actor_source_ids(db, state, info_owner, "NPC_NEW") == [
            "world_info:" + old.id
        ]
        assert await projection.actor_source_ids(db, state, info_owner, "MISSING") == []
        assert await projection.collect_documents(db, state, "foreign", actor_id="NPC_NEW") == []


@pytest.mark.parametrize(
    "audience,known,unresolved,visible",
    [
        ("common_knowledge", [], [], True),
        ("restricted", ["NPC_NEW"], [], True),
        ("restricted", ["NPC_NEW"], ["NPC_NEW"], False),
        ("restricted", ["OTHER"], [], False),
        ("narrator_only", [], [], False),
        ("common_knowledge", ["NPC_NEW"], [], False),
        ("restricted", ["NPC_NEW", "NPC_NEW"], [], False),
        ("restricted", ["NPC_NEW", 1], [], False),
        ("restricted", ["NPC_NEW"], ["OTHER"], False),
        ("restricted", {"NPC_NEW": True}, [], False),
    ],
)
async def test_actor_sql_matches_fail_closed_audience_contract(
    info_owner, audience, known, unresolved, visible
):
    async with TestSessionLocal() as db:
        _, _, entry = await seed_entry(db, info_owner)
        entry.audience, entry.known_by, entry.unresolved_known_by = audience, known, unresolved
        await db.commit()
        state = await _state(db)
        documents = await projection.collect_documents(
            db, state, info_owner, actor_id="NPC_NEW", query="archive"
        )
        assert bool(documents) is visible
        assert bool(await projection.actor_source_ids(db, state, info_owner, "NPC_NEW")) is visible


async def test_real_vectors_prefilter_sources_before_semantic_and_lexical_limits(tmp_path):
    scope = Scope("owner", "session", 1, "model")
    store = LanceMemoryStore(tmp_path / "vectors")
    documents = [
        dict(
            id=f"record-{index}",
            source_id=f"world_info:{index}",
            layer="world_info",
            source_hash="current",
            text="archive silver treaty",
            provenance="authored_reference",
        )
        for index in range(180)
    ]
    await store.upsert(scope, documents, [[1.0, 0.0]] * 180)
    allowed = [documents[-1]["source_id"]]
    rows = await store.query(scope, [1.0, 0.0], "silver treaty", source_ids=allowed, limit=1)
    assert [row["source_id"] for row in rows] == allowed
    assert await store.query(scope, [1.0, 0.0], "silver", source_ids=[], limit=32) == []


def test_actor_projection_rejects_every_non_reference_historical_layer():
    doc = MemoryDocument(
        id="one",
        user_id="owner",
        session_id="session",
        template_id=None,
        layer="session_note",
        source_id="secret",
        source_hash="hash",
        npc_id=None,
        scene_id=None,
        text="Private narrator knowledge",
        provenance="observed",
        source_message_ids=[],
        created_at="",
    )
    assert project([doc], audience="actor", actor_id="NPC", actual_npc_ids={"NPC"}) == ("", [])


async def test_selected_and_semantic_lookup_preserve_portable_non_uuid_identity(info_owner):
    async with TestSessionLocal() as db:
        _, _, entry = await seed_entry(db, info_owner, audience="common_knowledge")
        entry.id = "legacy:quoted'entry"
        await db.commit()
        state = await _state(db)
        source = "world_info:" + entry.id
        exact = await projection.collect_documents(
            db, state, info_owner, actor_id="NPC_NEW", source_ids=[source]
        )
        assert [document.source_id for document in exact] == [source]
        semantic = await projection.collect_documents(
            db,
            state,
            info_owner,
            actor_id="NPC_NEW",
            query="unmatched",
            candidates=[{"layer": "world_info", "source_id": source}],
        )
        assert semantic == exact
