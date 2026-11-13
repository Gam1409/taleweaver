"""Fictional owner workflows exercise the actual private HTTP surface."""

from copy import deepcopy
from unittest.mock import Mock

import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.api.routes.adventures import world_info, world_info_entries
from backend.engine.visual_novel.concurrency import session_write_lease
from backend.engine.world_info import limits
from backend.engine.world_info.portability import export_world_info
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.models.world_info import WorldInfoEntry, WorldInfoRevision
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import portrait_world
from tests.world_info_fixture import seed_corpus

__all__ = ["portrait_world"]
SID = "portrait-session"
URL = f"/api/adventures/{SID}/world-info"


@pytest_asyncio.fixture
async def corpus_api(portrait_world, monkeypatch):
    monkeypatch.setattr(world_info.worker, "schedule", Mock())
    monkeypatch.setattr(world_info_entries, "schedule_index", Mock())
    async with TestSessionLocal() as db:
        owner = await db.scalar(select(User.id))
        payload = await seed_corpus(db, SID, owner)
        await db.commit()
    return owner, payload


def update_payload(entry):
    return {
        key: deepcopy(entry[key])
        for key in (
            "version",
            "title",
            "summary",
            "kind",
            "audience",
            "known_by",
            "tags",
            "relations",
        )
    } | {"facts": [{"id": fact["id"], "text": fact["text"]} for fact in entry["facts"]]}


async def test_upload_is_session_only_immutable_and_does_not_start_model(
    auth_client, portrait_world, monkeypatch
):
    schedule = Mock()
    monkeypatch.setattr(world_info.worker, "schedule", schedule)
    response = await auth_client.post(
        URL + "/sources", files={"file": ("harbor.md", "灯台 opens at dawn.", "text/markdown")}
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["source"]["published_revision"] is None
    assert data["revision"]["status"] == "uploaded"
    assert data["revision"]["input_bytes"] > data["revision"]["input_characters"]
    schedule.assert_not_called()
    content = await auth_client.get(URL + f"/revisions/{data['revision']['id']}/content")
    assert content.json()["content"] == "灯台 opens at dawn."
    again = await auth_client.post(
        URL + "/sources", files={"file": ("harbor.md", "灯台 opens at dawn.")}
    )
    assert again.json()["duplicate"] is True
    assert again.json()["revision"]["id"] == data["revision"]["id"]
    foreign = await auth_client.get(
        f"/api/adventures/other-session/world-info/revisions/{data['revision']['id']}/content"
    )
    assert foreign.status_code == 404
    async with TestSessionLocal() as db:
        owner = await db.scalar(select(User.id))
        db.add(
            GameSession(
                id="parallel-session",
                user_id=owner,
                template_id="portrait-template",
                avatar_id="portrait-avatar",
            )
        )
        await db.commit()
    other = await auth_client.get("/api/adventures/parallel-session/world-info")
    assert other.json()["sources"] == []


@pytest.mark.parametrize(
    "filename,data",
    [
        ("notes.txt", "notes"),
        ("notes.json", '{"a":1,"a":2}'),
        ("notes.md", b"\xff"),
        ("notes.md", ""),
        ("notes.md", "a" * (limits.MAX_SOURCE_CHARACTERS + 1)),
    ],
)
async def test_bad_upload_keeps_previous_sources(auth_client, corpus_api, filename, data):
    response = await auth_client.post(URL + "/sources", files={"file": (filename, data)})
    assert response.status_code in {413, 422}, response.text
    overview = await auth_client.get(URL)
    assert len(overview.json()["sources"]) == 1


async def test_upload_authorizes_before_parsing_and_bounds_entire_stream(
    auth_client, portrait_world
):
    oversized = b"a" * (limits.MAX_SOURCE_BYTES + 20_000)
    denied = await auth_client.post(
        "/api/adventures/other-session/world-info/sources", files={"file": ("notes.md", oversized)}
    )
    assert denied.status_code == 404
    too_large = await auth_client.post(URL + "/sources", files={"file": ("notes.md", oversized)})
    assert too_large.status_code == 413
    repeated = await auth_client.post(
        URL + "/sources", files=[("file", ("a.md", "a")), ("file", ("b.md", "b"))]
    )
    assert repeated.status_code == 422


async def test_process_cancel_requires_current_control_version(
    auth_client, portrait_world, monkeypatch
):
    monkeypatch.setattr(world_info.worker, "schedule", Mock())
    uploaded = (
        await auth_client.post(
            URL + "/sources", files={"file": ("notes.md", "Lanterns guide ships.")}
        )
    ).json()
    rid = uploaded["revision"]["id"]
    start = await auth_client.post(URL + f"/revisions/{rid}/process", json={"control_version": 1})
    assert start.status_code == 200, start.text
    assert start.json()["revision"]["status"] == "queued"
    stale = await auth_client.post(URL + f"/revisions/{rid}/cancel", json={"control_version": 1})
    assert stale.status_code == 409
    stopped = await auth_client.post(URL + f"/revisions/{rid}/cancel", json={"control_version": 2})
    assert stopped.status_code == 200
    assert stopped.json()["revision"]["status"] == "cancelled"
    assert stopped.json()["revision"]["can_resume"]


async def test_published_edit_preserves_exact_evidence_cas_and_canonical_game_state(
    auth_client, corpus_api
):
    owner, corpus = corpus_api
    entry = corpus["entries"][0]
    before = await auth_client.get(URL + f"/entries/{entry['id']}")
    payload = update_payload(entry)
    payload["facts"][0]["text"] = "Lanterns mark the harbor entrance."
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == SID))
        previous = deepcopy((state.entity_states, state.in_game_time, state.quests))
    saved = await auth_client.put(URL + f"/entries/{entry['id']}", json=payload)
    assert saved.status_code == 200, saved.text
    fact = saved.json()["facts"][0]
    assert fact["evidence"] == before.json()["facts"][0]["evidence"]
    assert fact["original_text"] == before.json()["facts"][0]["original_text"]
    assert fact["edited"] and saved.json()["edited"]
    stale = await auth_client.put(URL + f"/entries/{entry['id']}", json=payload)
    assert stale.status_code == 409
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == SID))
        assert (state.entity_states, state.in_game_time, state.quests) == previous
        exported = await export_world_info(db, SID, owner)
        assert exported["entries"][0]["facts"][0]["text"] == fact["text"]


@pytest.mark.parametrize(
    "change",
    [
        {"known_by": ["MISSING"], "audience": "restricted"},
        {"known_by": ["NPC_NEW"], "audience": "common_knowledge"},
        {"relations": [{"target_id": "foreign", "kind": "related", "note": ""}]},
        {"facts": [{"id": "foreign", "text": "A new assertion."}]},
        {"facts": []},
        {"title": "x" * 161},
        {"tags": ["x" * 49]},
    ],
)
async def test_invalid_edits_never_replace_previous_entry(auth_client, corpus_api, change):
    entry = corpus_api[1]["entries"][0]
    original = (await auth_client.get(URL + f"/entries/{entry['id']}")).json()
    response = await auth_client.put(
        URL + f"/entries/{entry['id']}", json=update_payload(entry) | change
    )
    assert response.status_code == 422, response.text
    current = (await auth_client.get(URL + f"/entries/{entry['id']}")).json()
    assert current == original


async def test_delete_removes_incoming_links_updates_counters_and_remains_portable(
    auth_client, corpus_api
):
    owner, corpus = corpus_api
    target = corpus["entries"][1]
    deleted = await auth_client.delete(URL + f"/entries/{target['id']}?version=1")
    assert deleted.status_code == 200, deleted.text
    remaining = (await auth_client.get(URL + f"/entries/{corpus['entries'][0]['id']}")).json()
    assert remaining["relations"] == [] and remaining["version"] == 2
    async with TestSessionLocal() as db:
        revision = await db.get(WorldInfoRevision, target["source_revision_id"])
        assert revision.entries_count == revision.facts_count == 1
        exported = await export_world_info(db, SID, owner)
        assert len(exported["entries"]) == 1


async def test_published_replacement_is_explicit_and_atomic(auth_client, corpus_api):
    owner, corpus = corpus_api
    source = corpus["sources"][0]
    uploaded = await auth_client.post(
        URL + f"/sources/{source['id']}/revisions",
        files={"file": ("new.md", "A new navigation note.")},
        data={"expected_version": "2"},
    )
    assert uploaded.status_code == 201, uploaded.text
    active = (await auth_client.get(URL + "/entries?view=active")).json()
    assert active["total"] == 2
    async with TestSessionLocal() as db:
        original = await db.get(WorldInfoEntry, corpus["entries"][0]["id"])
        original.status = "draft"
        await db.commit()
    revision_id = corpus["revisions"][0]["id"]
    selection = {
        "revision_id": revision_id,
        "source_version": 3,
        "entries": [{"id": corpus["entries"][0]["id"], "version": 1}],
    }
    bad = await auth_client.post(
        URL + "/publish",
        json=selection | {"entries": [{"id": corpus["entries"][0]["id"], "version": 99}]},
    )
    assert bad.status_code == 409
    published = await auth_client.post(URL + "/publish", json=selection)
    assert published.status_code == 200, published.text
    assert published.json()["published"] == 1
    assert published.json()["index"]["status"] == "disabled"
    async with TestSessionLocal() as db:
        await export_world_info(db, SID, owner)


async def test_busy_gameplay_blocks_publication_but_not_upload_or_status(auth_client, corpus_api):
    entry = corpus_api[1]["entries"][0]
    with session_write_lease(SID):
        blocked = await auth_client.put(URL + f"/entries/{entry['id']}", json=update_payload(entry))
        assert blocked.status_code == 409
        uploaded = await auth_client.post(
            URL + "/sources", files={"file": ("quiet.md", "A quiet harbor.")}
        )
        assert uploaded.status_code == 201
        assert (await auth_client.get(URL)).status_code == 200


async def test_index_rebuild_respects_global_gate_and_is_session_scoped(auth_client, corpus_api):
    denied = await auth_client.post(URL + "/index/rebuild")
    assert denied.status_code == 409
    async with TestSessionLocal() as db:
        user = await db.get(User, corpus_api[0])
        user.llm_settings = {**(user.llm_settings or {}), "memory_rag": {"enabled": True}}
        await db.commit()
    rebuilt = await auth_client.post(URL + "/index/rebuild")
    assert rebuilt.status_code == 200, rebuilt.text
    assert rebuilt.json()["index"]["enabled"]
    assert not rebuilt.json()["index"]["paused"]
