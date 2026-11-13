"""Independent failure-boundary regressions for committed owner operations."""

import sqlite3
from unittest.mock import Mock

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from backend.api.routes.adventures import world_info, world_info_entries
from backend.models.memory_rag import MemoryIndexState
from backend.models.user import User
from backend.models.world_info import WorldInfoEntry, WorldInfoRevision, WorldInfoSource
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import portrait_world
from tests.test_world_info_api import SID, URL, corpus_api, update_payload

__all__ = ["portrait_world", "corpus_api"]


async def busy_response(*_args, **_kwargs):
    raise OperationalError(
        "SELECT response metadata", {}, sqlite3.OperationalError("database is locked")
    )


async def index_settings(owner, *, enabled=True, paused=False):
    async with TestSessionLocal() as db:
        user = await db.get(User, owner)
        user.llm_settings = {**(user.llm_settings or {}), "memory_rag": {"enabled": enabled}}
        db.add(MemoryIndexState(session_id=SID, user_id=owner, paused=paused))
        await db.commit()


async def test_committed_processing_is_scheduled_even_if_response_metadata_is_temporarily_busy(
    auth_client, portrait_world, monkeypatch
):
    uploaded = await auth_client.post(
        URL + "/sources", files={"file": ("archive.md", "The archive opens at dawn.")}
    )
    assert uploaded.status_code == 201
    revision_id = uploaded.json()["revision"]["id"]
    schedule = Mock()
    monkeypatch.setattr(world_info.worker, "schedule", schedule)

    monkeypatch.setattr(world_info.views, "revision_detail", busy_response)
    response = await auth_client.post(
        URL + f"/revisions/{revision_id}/process", json={"control_version": 1}
    )
    assert response.status_code == 409
    async with TestSessionLocal() as db:
        revision = await db.scalar(
            select(WorldInfoRevision).where(WorldInfoRevision.id == revision_id)
        )
        assert revision.status == "queued" and revision.control_version == 2
        assert revision.run_token is not None and revision.attempts == 0
        owner = revision.user_id
    schedule.assert_called_once_with("portrait-session", owner)


@pytest.mark.parametrize(
    "enabled,paused,active,scheduled",
    [
        (True, False, True, True),
        (True, True, True, False),
        (False, False, True, False),
        (True, False, False, False),
    ],
)
async def test_committed_edit_wakeup_precedes_response_and_preserves_gates(
    auth_client, corpus_api, monkeypatch, enabled, paused, active, scheduled
):
    owner, corpus = corpus_api
    await index_settings(owner, enabled=enabled, paused=paused)
    entry = corpus["entries"][0]
    if not active:
        async with TestSessionLocal() as db:
            row = await db.get(WorldInfoEntry, entry["id"])
            row.status = "draft"
            await db.commit()
    monkeypatch.setattr(world_info_entries.views, "entry_detail", busy_response)
    response = await auth_client.put(
        URL + f"/entries/{entry['id']}",
        json=update_payload(entry) | {"summary": "A reviewed note."},
    )
    assert response.status_code == 409
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoEntry, entry["id"])
        assert row.version == 2 and row.summary == "A reviewed note."
        index = await db.get(MemoryIndexState, SID)
        assert index.desired_revision == (2 if active else 1) and index.paused is paused
    assert world_info_entries.schedule_index.called is scheduled


async def test_committed_bulk_wakeup_precedes_response_index_query(
    auth_client, corpus_api, monkeypatch
):
    owner, corpus = corpus_api
    await index_settings(owner)
    body = {"action": "set_group", "group_name": "Archive", "filters": {"view": "active"}}
    preview = await auth_client.post(URL + "/entries/bulk/preview", json=body)
    assert preview.status_code == 200
    monkeypatch.setattr(world_info_entries.views, "index_state", busy_response)
    response = await auth_client.post(
        URL + "/entries/bulk/apply",
        json=body | {"selection_hash": preview.json()["selection_hash"]},
    )
    assert response.status_code == 409
    async with TestSessionLocal() as db:
        assert all(
            row.group_name == "Archive" and row.version == 2
            for row in await db.scalars(select(WorldInfoEntry))
        )
        index = await db.get(MemoryIndexState, SID)
        assert index.desired_revision == 2
    world_info_entries.schedule_index.assert_called_once_with(SID, owner)


async def test_committed_rebuild_wakeup_precedes_response_index_query(
    auth_client, corpus_api, monkeypatch
):
    owner, _ = corpus_api
    await index_settings(owner, paused=True)
    monkeypatch.setattr(world_info_entries.views, "index_state", busy_response)
    response = await auth_client.post(URL + "/index/rebuild")
    assert response.status_code == 409
    async with TestSessionLocal() as db:
        index = await db.get(MemoryIndexState, SID)
        assert not index.paused and index.desired_revision == 2
    world_info_entries.schedule_index.assert_called_once_with(SID, owner)


async def test_failed_precommit_wakeup_preparation_rolls_back_the_entry_and_dirty_marker(
    auth_client, corpus_api, monkeypatch
):
    _, corpus = corpus_api
    entry = corpus["entries"][0]
    monkeypatch.setattr(
        world_info_entries, "read_settings", Mock(side_effect=ValueError("Invalid settings"))
    )
    response = await auth_client.put(
        URL + f"/entries/{entry['id']}",
        json=update_payload(entry) | {"summary": "A new draft summary."},
    )
    assert response.status_code == 422
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoEntry, entry["id"])
        assert row.version == 1 and row.summary == entry["summary"]
        assert await db.get(MemoryIndexState, SID) is None
    world_info_entries.schedule_index.assert_not_called()


async def test_committed_publication_wakeup_precedes_source_response_query(
    auth_client, corpus_api, monkeypatch
):
    owner, corpus = corpus_api
    await index_settings(owner)
    entry = corpus["entries"][0]
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoEntry, entry["id"])
        row.status = "draft"
        await db.commit()
    monkeypatch.setattr(world_info_entries.views, "source_view", busy_response)
    response = await auth_client.post(
        URL + "/publish",
        json={
            "revision_id": entry["source_revision_id"],
            "source_version": 2,
            "entries": [{"id": entry["id"], "version": 1}],
        },
    )
    assert response.status_code == 409
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoEntry, entry["id"])
        assert row.status == "published" and row.version == 2
        source = await db.get(WorldInfoSource, entry["source_id"])
        assert source.version == 3
        assert (await db.get(MemoryIndexState, SID)).desired_revision == 2
    world_info_entries.schedule_index.assert_called_once_with(SID, owner)


async def test_committed_source_delete_cancels_processing_and_wakes_index_before_response(
    auth_client, corpus_api, monkeypatch
):
    owner, corpus = corpus_api
    await index_settings(owner)
    cancelled = Mock()
    monkeypatch.setattr(world_info_entries.worker, "cancel_source", cancelled)
    monkeypatch.setattr(world_info_entries.views, "index_state", busy_response)
    source_id = corpus["sources"][0]["id"]
    response = await auth_client.delete(URL + f"/sources/{source_id}?version=2")
    assert response.status_code == 409
    async with TestSessionLocal() as db:
        assert await db.get(WorldInfoSource, source_id) is None
        assert await db.scalar(select(WorldInfoEntry.id)) is None
        assert (await db.get(MemoryIndexState, SID)).desired_revision == 2
    cancelled.assert_called_once_with(source_id)
    world_info_entries.schedule_index.assert_called_once_with(SID, owner)


async def test_deeply_nested_mutation_json_returns_a_safe_validation_error(
    auth_client, portrait_world
):
    body = b'{"filters":' + b"[" * 2000 + b"0" + b"]" * 2000 + b"}"
    response = await auth_client.post(
        URL + "/entries/bulk/preview", content=body, headers={"content-type": "application/json"}
    )
    assert response.status_code == 422
    assert response.json() == {
        "detail": "Invalid World Info request. Check the file, fields and limits."
    }
