"""Book-sized sources stay paged in HTTP and bounded in processing memory."""

import re
from unittest.mock import Mock

from sqlalchemy import event, inspect, select

from backend.api.routes.adventures import world_info
from backend.engine.world_info import jobs, limits, plan_cache, queue, worker
from backend.engine.world_info.access import owned_revision
from backend.engine.world_info.views import revision_content
from backend.models.game_session import GameSession
from backend.models.world_info import WorldInfoEntry, WorldInfoRevision
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import portrait_world
from tests.test_world_info_jobs import seed_revision, world_info_owner
from tests.test_world_info_worker import fixture_entry

__all__ = ["portrait_world", "world_info_owner"]
SID = "portrait-session"
URL = f"/api/adventures/{SID}/world-info"
_RAW_CONTENT = re.compile(r"world_info_revisions\.content(?:\s|,|\))")


async def test_large_unicode_preview_uses_sql_pages_and_never_sends_the_whole_source(
    auth_client, portrait_world, monkeypatch
):
    text = "🧭 灯台 — Archive notes.\n" * 20000
    schedule = Mock()
    monkeypatch.setattr(world_info.worker, "schedule", schedule)
    uploaded = await auth_client.post(URL + "/sources", files={"file": ("archive-book.md", text)})
    assert uploaded.status_code == 201, uploaded.text
    rid = uploaded.json()["revision"]["id"]
    assert len(uploaded.content) < limits.MAX_PREVIEW_CHARACTERS
    queries = []

    def capture(_, __, statement, *___):
        if _RAW_CONTENT.search(statement):
            queries.append(statement)

    engine = TestSessionLocal.kw["bind"].sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        metadata = await auth_client.get(URL + f"/revisions/{rid}")
        assert metadata.status_code == 200
        assert not queries
        for offset, limit in [(0, 8000), (8000, 8000), (len(text) - 30, 8000)]:
            page = await auth_client.get(
                URL + f"/revisions/{rid}/content?offset={offset}&limit={limit}"
            )
            assert page.status_code == 200, page.text
            data = page.json()
            assert data["content"] == text[offset : offset + limit]
            assert data["offset"] == offset and data["total_characters"] == len(text)
            assert data["input_bytes"] == len(text.encode())
            assert data["input_characters"] == len(text)
            expected_next = offset + len(data["content"])
            assert data["next_offset"] == (expected_next if expected_next < len(text) else None)
            assert len(data["content"]) <= limits.MAX_PREVIEW_CHARACTERS
        assert len(queries) == 3 and all("substr(" in statement.lower() for statement in queries)
        queries.clear()
        denied = await auth_client.get(
            f"/api/adventures/other-session/world-info/revisions/{rid}/content"
        )
        assert denied.status_code == 404 and not queries
        invalid = await auth_client.get(URL + f"/revisions/{rid}/content?limit=8001")
        assert invalid.status_code == 422 and not queries
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    schedule.assert_not_called()


async def test_metadata_access_and_a_preview_page_leave_raw_body_unloaded(world_info_owner):
    rid = await seed_revision(world_info_owner, content="A" * 20000)
    async with TestSessionLocal() as db:
        revision = await owned_revision(db, world_info_owner, SID, rid)
        assert "content" in inspect(revision).unloaded
        page = await revision_content(db, revision, offset=8000, limit=100)
        assert page.content == "A" * 100 and page.next_offset == 8100
        assert "content" in inspect(revision).unloaded
        full = await owned_revision(db, world_info_owner, SID, rid, include_content=True)
        assert full.content == "A" * 20000


async def test_processing_reuses_one_large_plan_and_retains_generated_groups(
    world_info_owner, monkeypatch
):
    owner = world_info_owner
    rid = await seed_revision(owner, content="A" * 400000)
    parse = Mock(wraps=jobs.parse_source)
    monkeypatch.setattr(jobs, "parse_source", parse)
    references = []

    async def extract(user, sid, revision_id, source_hash, batch, existing, **kwargs):
        await kwargs["before_request"]()
        references.append(existing)
        return [
            fixture_entry(revision_id, source_hash, batch).model_copy(
                update={"group_name": "Archive documents"}
            )
        ]

    monkeypatch.setattr(worker, "extract_batch", extract)
    reads = []

    def capture(_, __, statement, *___):
        if _RAW_CONTENT.search(statement):
            reads.append(statement)

    engine = TestSessionLocal.kw["bind"].sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        for _ in range(2):
            claim = await queue.claim_next(SID, owner)
            assert claim is not None
            await worker.process_claim(claim)
        assert parse.call_count == 1 and len(reads) == 1
        assert references[0] == ()
        assert references[1][0].group_name == "Archive documents"
        assert len(plan_cache._plans) == 1
        async with TestSessionLocal() as db:
            revision = await db.get(WorldInfoRevision, rid)
            assert revision.cursor == revision.attempts == revision.entries_count == 2
            assert revision.total_batches > 2 and revision.status == "queued"
            entries = list(await db.scalars(select(WorldInfoEntry)))
            assert all(entry.group_name == "Archive documents" for entry in entries)
            await jobs.cancel_processing(db, owner, SID, rid, revision.control_version)
            await db.commit()
        worker.cancel_local(rid)
        assert not plan_cache._plans
    finally:
        event.remove(engine, "before_cursor_execute", capture)


async def test_parsing_cache_is_bounded_and_keeps_one_revision_per_session(world_info_owner):
    owner = world_info_owner
    sessions = [f"book-session-{number}" for number in range(plan_cache.MAX_CACHED_SESSIONS + 1)]
    async with TestSessionLocal() as db:
        db.add_all(
            GameSession(id=sid, user_id=owner, avatar_id="portrait-avatar") for sid in sessions
        )
        await db.commit()
    for sid in sessions:
        rid = await seed_revision(owner, session_id=sid)
        async with TestSessionLocal() as db:
            revision = await owned_revision(db, owner, sid, rid)
            await plan_cache.load(db, revision)
    assert len(plan_cache._plans) == plan_cache.MAX_CACHED_SESSIONS
    assert sessions[0] not in plan_cache._plans
    last = sessions[-1]
    rid = await seed_revision(owner, session_id=last, content="Another archive reference.")
    async with TestSessionLocal() as db:
        revision = await owned_revision(db, owner, last, rid)
        await plan_cache.load(db, revision)
    assert len(plan_cache._plans) == plan_cache.MAX_CACHED_SESSIONS
    assert plan_cache._plans[last].revision_id == rid
