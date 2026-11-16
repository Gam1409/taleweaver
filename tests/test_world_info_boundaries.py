"""Public numeric controls reject unrepresentable values before storage work."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import select

from backend.api.routes.adventures import world_info, world_info_upload
from backend.engine.world_info import jobs, limits, queue
from backend.engine.world_info.access import WorldInfoError, compare_version
from backend.engine.world_info.portability import copy_world_info, export_world_info
from backend.models.game_session import GameSession
from backend.models.user import User
from backend.models.world_info import WorldInfoRevision, WorldInfoSource
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import portrait_world
from tests.test_world_info_jobs import seed_revision, world_info_owner
from tests.world_info_fixture import seed_corpus

__all__ = ["portrait_world", "world_info_owner"]
SID = "portrait-session"
URL = f"/api/adventures/{SID}/world-info"
HUGE = 10**80


@pytest.mark.parametrize(
    "operation", ["start", "cancel", "delete_entry", "unpublish", "delete_source"]
)
async def test_large_versions_are_safe_http_errors(
    auth_client, portrait_world, monkeypatch, operation
):
    schedule = Mock()
    monkeypatch.setattr(world_info.worker, "schedule", schedule)
    if operation in {"start", "cancel"}:
        upload = await auth_client.post(
            URL + "/sources", files={"file": ("note.md", "Lanterns guide ships.")}
        )
        rid = upload.json()["revision"]["id"]
        action = "process"
        if operation == "cancel":
            started = await auth_client.post(
                URL + f"/revisions/{rid}/process", json={"control_version": 1}
            )
            assert started.status_code == 200
            action = "cancel"
        before = schedule.call_count
        response = await auth_client.post(
            URL + f"/revisions/{rid}/{action}", json={"control_version": HUGE}
        )
        assert schedule.call_count == before
    else:
        async with TestSessionLocal() as db:
            owner = await db.scalar(select(User.id))
            corpus = await seed_corpus(db, SID, owner)
            await db.commit()
        eid = corpus["entries"][0]["id"]
        if operation == "unpublish":
            response = await auth_client.post(
                URL + f"/entries/{eid}/unpublish", json={"version": HUGE}
            )
        elif operation == "delete_source":
            source_id = corpus["sources"][0]["id"]
            response = await auth_client.delete(URL + f"/sources/{source_id}?version={HUGE}")
        else:
            response = await auth_client.delete(URL + f"/entries/{eid}?version={HUGE}")
    assert response.status_code == 422, response.text


async def test_large_pagination_offset_is_a_safe_http_error(auth_client, portrait_world):
    response = await auth_client.get(URL + f"/entries?offset={HUGE}")
    assert response.status_code == 422, response.text


async def test_multipart_source_version_accepts_the_full_safe_counter_range(
    auth_client, portrait_world
):
    async with TestSessionLocal() as db:
        owner = await db.scalar(select(User.id))
        corpus = await seed_corpus(db, SID, owner)
        source = await db.get(WorldInfoSource, corpus["sources"][0]["id"])
        source.version = 10**11
        await db.commit()
    response = await auth_client.post(
        URL + f"/sources/{source.id}/revisions",
        files={"file": ("replacement.md", "A new navigation note.")},
        data={"expected_version": str(10**11)},
    )
    assert response.status_code == 201, response.text


async def test_upload_tempfiles_close_even_when_form_cleanup_is_cancelled(monkeypatch):
    temporary = Mock()
    form = SimpleNamespace(
        multi_items=lambda: [],
        keys=lambda: [],
        get=lambda _: None,
        close=AsyncMock(side_effect=asyncio.CancelledError),
    )
    parser = SimpleNamespace(
        parse=AsyncMock(return_value=form), _files_to_close_on_error=[temporary]
    )
    monkeypatch.setattr(world_info_upload, "MultiPartParser", lambda *_, **__: parser)
    request = SimpleNamespace(headers={"content-type": "multipart/form-data; boundary=fictional"})
    with pytest.raises(asyncio.CancelledError):
        await world_info_upload.read_upload(request)
    temporary.close.assert_called_once()


def test_saved_counter_and_request_bounds_agree():
    from pydantic import ValidationError

    from backend.engine.world_info.schemas import ControlVersion, SavedVersion, Version

    assert SavedVersion(version=limits.MAX_COUNTER).version == limits.MAX_COUNTER
    assert Version(version=limits.MAX_COUNTER - 1).version == limits.MAX_COUNTER - 1
    for contract in (ControlVersion, Version):
        name = "control_version" if contract is ControlVersion else "version"
        with pytest.raises(ValidationError):
            contract(**{name: limits.MAX_COUNTER})


async def test_direct_counter_callers_do_not_bind_out_of_range_values(world_info_owner):
    rid = await seed_revision(world_info_owner, status="uploaded")
    async with TestSessionLocal() as db:
        revision = await db.get(WorldInfoRevision, rid)
        source = await db.get(WorldInfoSource, revision.source_id)
        with pytest.raises(WorldInfoError):
            await compare_version(db, source, HUGE)
        with pytest.raises(jobs.JobConflictError):
            await jobs.start_processing(db, world_info_owner, SID, rid, HUGE)
        await db.rollback()
        await db.refresh(revision)
        await db.refresh(source)
        assert source.version == revision.control_version == 1
        assert revision.status == "uploaded" and revision.run_token is None


async def test_terminal_controls_cannot_start_a_job_that_cannot_be_cancelled(world_info_owner):
    from backend.engine.world_info.view_records import job_record

    rid = await seed_revision(world_info_owner, status="uploaded")
    async with TestSessionLocal() as db:
        revision = await db.get(WorldInfoRevision, rid)
        revision.control_version = limits.MAX_COUNTER - 1
        await db.commit()
        with pytest.raises(jobs.JobConflictError, match="exhausted"):
            await jobs.start_processing(db, world_info_owner, SID, rid, limits.MAX_COUNTER - 1)
        await db.rollback()
        await db.refresh(revision)
        source = await db.get(WorldInfoSource, revision.source_id)
        assert not job_record(revision, source, (0, 0)).can_start
        assert revision.status == "uploaded" and revision.run_token is None


async def test_terminal_source_fence_and_portable_invalidation_remain_representable(
    world_info_owner,
):
    owner = world_info_owner
    rid = await seed_revision(owner)
    async with TestSessionLocal() as db:
        revision = await db.get(WorldInfoRevision, rid)
        revision.control_version = limits.MAX_COUNTER
        revision.attempts = limits.MAX_COUNTER
        await db.commit()
        await jobs.fence_source(db, owner, SID, revision.source_id)
        await db.commit()
        await db.refresh(revision)
        assert revision.status == "cancelled" and revision.control_version == limits.MAX_COUNTER
        assert revision.run_token is revision.lease_token is None
        await export_world_info(db, SID, owner)
        db.add(GameSession(id="boundary-copy", user_id=owner, avatar_id="portrait-avatar"))
        await db.flush()
        await copy_world_info(db, SID, "boundary-copy", owner)
        await db.commit()
        copied = await export_world_info(db, "boundary-copy", owner)
        assert copied["revisions"][0]["control_version"] == limits.MAX_COUNTER
        assert copied["revisions"][0]["attempts"] == limits.MAX_COUNTER


async def test_exhausted_request_counter_stops_before_another_dispatch(world_info_owner):
    rid = await seed_revision(world_info_owner)
    async with TestSessionLocal() as db:
        revision = await db.get(WorldInfoRevision, rid)
        revision.attempts = limits.MAX_COUNTER
        await db.commit()
    claim = await queue.claim_next(SID, world_info_owner)
    assert claim is not None
    with pytest.raises(queue.CounterLimitError):
        await queue.reserve_request(claim)
    async with TestSessionLocal() as db:
        revision = await db.get(WorldInfoRevision, rid)
        assert revision.attempts == limits.MAX_COUNTER and revision.cursor == 0


@pytest.mark.parametrize(
    "row,key",
    [
        ("sources", "version"),
        ("entries", "version"),
        ("revisions", "control_version"),
        ("revisions", "attempts"),
    ],
)
def test_portable_counters_reject_values_that_cannot_roundtrip(row, key):
    from pydantic import ValidationError

    from backend.engine.world_info.portable_schema import PortableWorldInfo
    from tests.world_info_fixture import corpus

    payload = corpus()
    payload[row][0][key] = HUGE
    with pytest.raises(ValidationError):
        PortableWorldInfo.model_validate(payload)
