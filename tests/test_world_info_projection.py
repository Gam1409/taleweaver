"""Current accepted SQL references own recall even when vectors are stale or absent."""

from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from backend.engine.memory_rag import documents, recall_sources, retrieval
from backend.engine.memory_rag.prompts import recall_block
from backend.engine.memory_rag.store import Scope
from backend.engine.world_info import projection
from backend.engine.world_info.types import EntryDraft, entry_hash, searchable_text
from backend.models.game_session import GameSession
from backend.models.memory_rag import MemoryIndexState
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.models.world_entity import WorldEntity
from backend.models.world_info import WorldInfoEntry, WorldInfoRevision, WorldInfoSource
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import portrait_world
from tests.world_info_projection_fixture import seed_entry

__all__ = ["portrait_world"]


@pytest.fixture
async def info_owner(portrait_world):
    async with TestSessionLocal() as db:
        return await db.scalar(
            select(GameSession.user_id).where(GameSession.id == "portrait-session")
        )


async def _state(db, sid="portrait-session"):
    return await db.scalar(select(SessionState).where(SessionState.session_id == sid))


async def test_two_sessions_of_one_template_have_independent_author_references(info_owner):
    owner = info_owner
    async with TestSessionLocal() as db:
        state = await _state(db)
        db.add(
            GameSession(
                id="sibling",
                user_id=owner,
                template_id=state.template_id,
                avatar_id=state.avatar_id,
            )
        )
        db.add(
            SessionState(
                session_id="sibling",
                template_id=state.template_id,
                avatar_id=state.avatar_id,
                current_scene_id=state.current_scene_id,
                entity_states={},
            )
        )
        await seed_entry(db, owner, text="The archive opens at dawn.")
        await seed_entry(db, owner, sid="sibling", text="The archive opens at midnight.")
        await db.commit()
        for sid, expected, forbidden in (
            ("portrait-session", "dawn", "midnight"),
            ("sibling", "midnight", "dawn"),
        ):
            current = await _state(db, sid)
            full = await documents.collect_documents(db, current, owner)
            foreground = await recall_sources.collect_documents(db, current, owner, query="archive")
            assert [doc for doc in full if doc.layer == projection.LAYER] == foreground
            assert expected in foreground[0].text and forbidden not in str(foreground)
            assert foreground[0].source_message_ids == []
            assert foreground[0].provenance == "authored_reference"
            assert await projection.collect_documents(db, current, "foreign") == []


async def test_new_draft_does_not_replace_the_active_published_revision(info_owner):
    owner = info_owner
    async with TestSessionLocal() as db:
        source, _, _ = await seed_entry(db, owner)
        source.current_revision = 2
        db.add(
            WorldInfoRevision(
                source_id=source.id,
                user_id=owner,
                session_id=source.session_id,
                number=2,
                filename="new.md",
                format="md",
                content="Future unpublished notes.",
                content_hash="b" * 64,
                input_bytes=25,
                input_characters=25,
            )
        )
        await seed_entry(db, owner, text="A draft secret remains hidden.", status="draft")
        await db.commit()
        rows = await projection.collect_documents(db, await _state(db), owner)
        assert len(rows) == 1 and "dawn" in rows[0].text
        assert "Future" not in str(rows) and "hidden" not in str(rows)
        source.version += 1
        source.filename = "replacement.md"
        await db.commit()
        active = (await projection.collect_documents(db, await _state(db), owner))[0]
        assert active.source_hash == rows[0].source_hash
        assert active.source_attribution["filename"] == "notes.md"
        source.published_revision = 2
        await db.commit()
        assert await projection.collect_documents(db, await _state(db), owner) == []


@pytest.mark.parametrize(
    "audience,known_by",
    [
        ("restricted", []),
        ("common_knowledge", ["NPC_NEW"]),
        ("unknown", []),
    ],
)
async def test_invalid_imported_visibility_is_fail_closed(info_owner, audience, known_by):
    async with TestSessionLocal() as db:
        await seed_entry(db, info_owner, audience=audience, known_by=known_by)
        await db.commit()
        assert await projection.collect_documents(db, await _state(db), info_owner) == []


@pytest.mark.parametrize(
    "model,field,value",
    [
        (WorldInfoEntry, "user_id", "foreign"),
        (WorldInfoSource, "session_id", "other-session"),
        (WorldInfoRevision, "user_id", "foreign"),
    ],
)
async def test_every_joined_source_owner_is_checked(info_owner, model, field, value):
    async with TestSessionLocal() as db:
        source, revision, entry = await seed_entry(db, info_owner)
        row = {WorldInfoSource: source, WorldInfoRevision: revision, WorldInfoEntry: entry}[model]
        setattr(row, field, value)
        await db.commit()
        assert await projection.collect_documents(db, await _state(db), info_owner) == []


async def test_scope_only_edit_changes_canonical_hash_without_changing_statement(info_owner):
    owner = info_owner
    async with TestSessionLocal() as db:
        _, _, entry = await seed_entry(db, owner)
        await db.commit()
        state = await _state(db)
        before = (await projection.collect_documents(db, state, owner))[0]
        entry.audience = "common_knowledge"
        await db.commit()
        after = (await projection.collect_documents(db, state, owner))[0]
        assert before.id == after.id and before.text == after.text
        assert before.source_hash != after.source_hash
        scope = Scope(owner, state.session_id, 2, "model")
        stale = before.to_dict() | {"epoch": 2, "signature": "model"}
        assert retrieval._canonical_scores([after], [stale], scope) == {}


async def test_bounded_foreground_finds_old_lexical_and_semantic_entries(info_owner):
    async with TestSessionLocal() as db:
        source, revision, original = await seed_entry(db, info_owner)
        old_id = ""
        for index in range(81):
            facts = deepcopy(original.facts)
            facts[0]["id"] = str(uuid4())
            draft = EntryDraft(
                id=str(uuid4()),
                title="Rare aquamarine treaty" if index == 0 else f"Record {index}",
                facts=facts,
            )
            if index == 0:
                old_id = draft.id
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
        state = await _state(db)
        full = await projection.collect_documents(db, state, info_owner)
        old = next(doc for doc in full if doc.source_id == f"world_info:{old_id}")
        lexical = await projection.collect_documents(db, state, info_owner, query="aquamarine")
        semantic = await projection.collect_documents(
            db, state, info_owner, query="unmatched", candidates=[old.to_dict()]
        )
        recent = await projection.collect_documents(db, state, info_owner, query="unmatched")
        assert len(full) == 82 and len(recent) == projection.RECENT_ENTRIES
        assert old not in recent and old in lexical and old in semantic
        assert len(lexical) <= projection.RECENT_ENTRIES + projection.LEXICAL_ENTRIES
        assert len(semantic) <= projection.RECENT_ENTRIES + projection.SEMANTIC_ENTRIES


@pytest.mark.parametrize("change", ["delete", "scope"])
async def test_embedding_await_cannot_resurrect_deleted_or_reclassified_reference(
    info_owner, monkeypatch, change
):
    owner = info_owner
    async with TestSessionLocal() as db:
        source, _, entry = await seed_entry(db, owner, audience="common_knowledge")
        db.add(
            MemoryIndexState(
                session_id="portrait-session",
                user_id=owner,
                template_id="portrait-template",
                epoch=2,
                signature="model",
                indexed_revision=1,
            )
        )
        user = await db.get(User, owner)
        user.llm_settings = {"memory_rag": {"enabled": True}}
        await db.commit()
        state = await _state(db)
        old = (await projection.collect_documents(db, state, owner))[0]
        scope = Scope(owner, state.session_id, 2, "model")
        await db.commit()

        async def delayed_candidates(*_args):
            async with TestSessionLocal() as writer:
                if change == "delete":
                    await writer.execute(
                        delete(WorldInfoEntry).where(WorldInfoEntry.id == entry.id)
                    )
                    await writer.execute(
                        delete(WorldInfoRevision).where(WorldInfoRevision.source_id == source.id)
                    )
                    await writer.execute(
                        delete(WorldInfoSource).where(WorldInfoSource.id == source.id)
                    )
                else:
                    current = await writer.get(WorldInfoEntry, entry.id)
                    current.audience = "narrator_only"
                    current.version += 1
                await writer.commit()
            return [old.to_dict() | {"epoch": 2, "signature": "model"}], scope

        monkeypatch.setattr(retrieval, "_semantic_candidates", delayed_candidates)
        host = SimpleNamespace(db=db, user=user, state=state)
        recall = await retrieval.prepare_recall(host, "archive", [])
        assert recall.method == "sql_lexical"
        host._memory_recall = recall
        assert "dawn" not in recall_block(host, "vn_social")
        assert ("dawn" in recall_block(host, "narrator")) == (change == "scope")


@pytest.mark.parametrize("index_mode", ["paused", "failure", "off"])
async def test_published_reference_keeps_existing_pause_failure_and_off_semantics(
    info_owner, monkeypatch, index_mode
):
    owner = info_owner
    async with TestSessionLocal() as db:
        await seed_entry(db, owner)
        user = await db.get(User, owner)
        user.llm_settings = {"memory_rag": {"enabled": index_mode != "off"}}
        db.add(
            MemoryIndexState(
                session_id="portrait-session",
                user_id=owner,
                template_id="portrait-template",
                paused=index_mode == "paused",
                signature="model",
                indexed_revision=1,
            )
        )
        await db.commit()
        embed = AsyncMock(side_effect=TimeoutError("Mocked provider outage"))
        monkeypatch.setattr(retrieval, "embed_texts", embed)
        host = SimpleNamespace(db=db, state=await _state(db), user=user)
        recall = await retrieval.prepare_recall(host, "archive", [])
        assert recall.enabled == (index_mode != "off")
        assert len(recall.documents) == (0 if index_mode == "off" else 1)
        assert embed.await_count == (1 if index_mode == "failure" else 0)


@pytest.mark.parametrize("stored_unresolved", [False, True])
async def test_missing_recipient_remains_narrator_reference_and_restores_only_local_knowledge(
    info_owner, stored_unresolved
):
    async with TestSessionLocal() as db:
        _, _, entry = await seed_entry(db, info_owner, audience="restricted", known_by=["NPC_NEW"])
        if stored_unresolved:
            entry.unresolved_known_by = ["NPC_NEW"]
        await db.commit()
        state = await _state(db)
        original = (await projection.collect_documents(db, state, info_owner))[0]
        await db.execute(
            delete(WorldEntity).where(
                WorldEntity.session_id == state.session_id, WorldEntity.id == "NPC_NEW"
            )
        )
        await db.commit()
        missing = (await projection.collect_documents(db, state, info_owner))[0]
        assert missing.known_by == missing.unresolved_known_by == ("NPC_NEW",)
        assert projection.visible_to(missing, "narrator")
        assert not projection.visible_to(missing, "actor", actor_id="NPC_NEW")
        assert not projection.visible_to(missing, "vn_social")
        assert (missing.source_hash == original.source_hash) == stored_unresolved
        db.add(
            WorldEntity(
                id="NPC_NEW",
                session_id=state.session_id,
                entity_type="NPC",
                name="Restored NPC",
                description="A restored canonical identity.",
                current_scene_id=state.current_scene_id,
            )
        )
        await db.commit()
        restored = (await projection.collect_documents(db, state, info_owner))[0]
        assert projection.visible_to(
            restored, "actor", actor_id="NPC_NEW", actual_npc_ids={"NPC_NEW"}
        ) == (not stored_unresolved)
        assert restored.source_hash == original.source_hash


async def test_publication_invalidates_derived_work_in_callers_transaction_and_keeps_pause(
    info_owner,
):
    owner = info_owner
    async with TestSessionLocal() as db:
        db.add(
            MemoryIndexState(
                session_id="portrait-session",
                user_id=owner,
                paused=True,
                status="paused",
                epoch=4,
                desired_revision=7,
                lease_token="old-work",
                signature="old-model",
            )
        )
        await db.commit()
        await projection.mark_changed(db, owner, "portrait-session")
        row = await db.get(MemoryIndexState, "portrait-session")
        assert row.epoch == 5 and row.paused and row.status == "paused"
        assert row.desired_revision == 8
        assert row.lease_token is None and row.signature is None
        assert db.info["world_info_changed"] is True
        await db.rollback()
        await db.refresh(row)
        assert row.epoch == 4 and row.lease_token == "old-work"
        assert row.desired_revision == 7
        db.info.pop("world_info_changed")
        with pytest.raises(ValueError, match="ownership"):
            await projection.mark_changed(db, "foreign", "portrait-session")
        assert not db.info.get("world_info_changed")
