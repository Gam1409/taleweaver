"""Publication lifecycle and scheduler boundaries use actual versioned API writes."""

from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import select

from backend.api.routes.adventures import world_info_entries
from backend.engine.world_info.portability import export_world_info
from backend.engine.world_info.types import EntryDraft, entry_hash, searchable_text
from backend.models.memory_rag import MemoryIndexState
from backend.models.user import User
from backend.models.world_info import WorldInfoEntry, WorldInfoRevision, WorldInfoSource
from tests.conftest import TestSessionLocal
from tests.test_world_info_api import SID, URL, corpus_api, portrait_world, update_payload

__all__ = ["corpus_api", "portrait_world"]


@pytest.mark.parametrize(
    "enabled,paused,scheduled", [(False, False, False), (True, True, False), (True, False, True)]
)
async def test_active_edits_only_schedule_enabled_unpaused_index(
    auth_client, corpus_api, enabled, paused, scheduled
):
    owner, corpus = corpus_api
    async with TestSessionLocal() as db:
        user = await db.get(User, owner)
        user.llm_settings = {**(user.llm_settings or {}), "memory_rag": {"enabled": enabled}}
        db.add(
            MemoryIndexState(
                session_id=SID, user_id=owner, template_id="portrait-template", paused=paused
            )
        )
        await db.commit()
    entry = corpus["entries"][0]
    response = await auth_client.put(URL + f"/entries/{entry['id']}", json=update_payload(entry))
    assert response.status_code == 200, response.text
    assert world_info_entries.schedule_index.called is scheduled
    async with TestSessionLocal() as db:
        index = await db.get(MemoryIndexState, SID)
        assert index.paused is paused
        assert index.desired_revision == 2


async def test_draft_edit_does_not_dirty_or_start_memory_maintenance(auth_client, corpus_api):
    owner, corpus = corpus_api
    entry = corpus["entries"][0]
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoEntry, entry["id"])
        row.status = "draft"
        user = await db.get(User, owner)
        user.llm_settings = {**(user.llm_settings or {}), "memory_rag": {"enabled": True}}
        await db.commit()
    response = await auth_client.put(URL + f"/entries/{entry['id']}", json=update_payload(entry))
    assert response.status_code == 200
    world_info_entries.schedule_index.assert_not_called()
    async with TestSessionLocal() as db:
        assert await db.get(MemoryIndexState, SID) is None


async def test_fact_removal_updates_current_counts_without_losing_evidence(auth_client, corpus_api):
    owner, corpus = corpus_api
    entry = corpus["entries"][0]
    second = deepcopy(entry["facts"][0])
    second["id"] = str(uuid4())
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoEntry, entry["id"])
        row.facts = [*row.facts, second]
        draft = EntryDraft.model_validate(
            {key: getattr(row, key) for key in EntryDraft.model_fields}
        )
        row.content_hash, row.search_text = entry_hash(draft), searchable_text(draft)
        revision = await db.get(WorldInfoRevision, row.source_revision_id)
        revision.facts_count = 3
        await db.commit()
    updated = await auth_client.put(URL + f"/entries/{entry['id']}", json=update_payload(entry))
    assert updated.status_code == 200, updated.text
    assert updated.json()["facts"] == [entry["facts"][0] | {"edited": False}]
    async with TestSessionLocal() as db:
        exported = await export_world_info(db, SID, owner)
        assert exported["revisions"][0]["facts_count"] == 2
        assert sum(len(row["facts"]) for row in exported["entries"]) == 2


async def test_unpublish_and_delete_source_remove_only_owned_knowledge(auth_client, corpus_api):
    owner, corpus = corpus_api
    source, entry = corpus["sources"][0], corpus["entries"][0]
    detail = await auth_client.get(URL + f"/sources/{source['id']}")
    assert detail.status_code == 200 and len(detail.json()["revisions"]) == 2
    unpublished = await auth_client.post(
        URL + f"/entries/{entry['id']}/unpublish", json={"version": 1}
    )
    assert unpublished.status_code == 200
    assert not unpublished.json()["is_active"]
    assert (await auth_client.get(URL + "/entries?view=active")).json()["total"] == 1
    denied = await auth_client.delete(
        f"/api/adventures/other-session/world-info/sources/{source['id']}?version=2"
    )
    assert denied.status_code == 404
    stale = await auth_client.delete(URL + f"/sources/{source['id']}?version=1")
    assert stale.status_code == 409
    deleted = await auth_client.delete(URL + f"/sources/{source['id']}?version=2")
    assert deleted.status_code == 200, deleted.text
    assert (await auth_client.get(URL)).json()["sources"] == []
    async with TestSessionLocal() as db:
        assert (
            await db.scalar(select(WorldInfoSource.id).where(WorldInfoSource.user_id == owner))
            is None
        )
        assert (
            await db.scalar(select(WorldInfoRevision.id).where(WorldInfoRevision.user_id == owner))
            is None
        )
        assert (
            await db.scalar(select(WorldInfoEntry.id).where(WorldInfoEntry.user_id == owner))
            is None
        )
