"""Turn and pace JSON writes cannot interleave in the standard single-worker server."""

import asyncio
from contextlib import aclosing
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.engine.visual_novel.concurrency import (
    SessionBusyError,
    _active_sessions,
    guard_session_turn,
    session_write_lease,
)
from backend.engine.visual_novel.config import SETTINGS_KEY
from backend.engine.visual_novel.schema import STATE_KEY
from backend.engine.visual_novel.state import load_state, save_state
from backend.models.session_state import SessionState
from backend.models.user import User
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import portrait_world
from tests.test_vn_lifecycle import SESSION, social_fixture, vn_world

__all__ = ["portrait_world", "vn_world"]


async def collect(stream):
    async with aclosing(stream):
        return [chunk async for chunk in stream]


@pytest.mark.asyncio
async def test_real_manager_lease_prevents_lost_pace_and_social_writes(
    auth_client, vn_world, monkeypatch
):
    loaded = asyncio.Event()
    resume = asyncio.Event()

    async def paused_inner(manager, *_args, **_kwargs):
        # The actual process_turn decorator must acquire before any state read.
        with pytest.raises(SessionBusyError), session_write_lease(manager.game_id):
            pass
        state = await manager.db.scalar(
            select(SessionState).where(SessionState.session_id == SESSION)
        )
        loaded.set()
        await resume.wait()
        social = load_state(state)
        social.turn += 1
        save_state(state, social)
        await manager.db.commit()
        yield "event: status\ndata: {}\n\n"

    monkeypatch.setattr(GameTurnManager, "_process_turn_inner", paused_inner)
    async with TestSessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == "test_user"))
        manager = GameTurnManager(db, SESSION, user)
        task = asyncio.create_task(collect(manager.process_turn("Continue")))
        try:
            await asyncio.wait_for(loaded.wait(), timeout=2)
            response = await asyncio.wait_for(
                auth_client.patch(
                    f"/api/adventures/{SESSION}/vn-settings",
                    json={"pace": "brisk"},
                ),
                timeout=2,
            )
            assert response.status_code == 409
            assert "Wait for the current turn" in response.json()["detail"]
            assert not task.done()
        finally:
            resume.set()
            await asyncio.wait_for(task, timeout=2)
    response = await auth_client.patch(
        f"/api/adventures/{SESSION}/vn-settings", json={"pace": "brisk"}
    )
    assert response.status_code == 200
    async with TestSessionLocal() as db:
        saved = await db.scalar(select(SessionState).where(SessionState.session_id == SESSION))
        assert saved.entity_states[SETTINGS_KEY] == {"pace": "brisk"}
        assert saved.entity_states[STATE_KEY]["turn"] == social_fixture().turn + 1
        assert (
            saved.entity_states[STATE_KEY]["characters"]
            == social_fixture().model_dump()["characters"]
        )
    assert SESSION not in _active_sessions


@pytest.mark.asyncio
async def test_pace_write_lease_blocks_turn_before_initialization(
    auth_client, vn_world, monkeypatch
):
    from backend.api.routes.adventures import vn_settings

    entered, resume = asyncio.Event(), asyncio.Event()
    owned = vn_settings.owned_vn_state

    async def paused_owned(*args):
        state = await owned(*args)
        entered.set()
        await resume.wait()
        return state

    async def must_not_initialize(*_args, **_kwargs):
        pytest.fail("A busy turn must not enter initialization or mutate state")
        yield "unreachable"

    monkeypatch.setattr(vn_settings, "owned_vn_state", paused_owned)
    monkeypatch.setattr(GameTurnManager, "_process_turn_inner", must_not_initialize)
    request = asyncio.create_task(
        auth_client.patch(f"/api/adventures/{SESSION}/vn-settings", json={"pace": "balanced"})
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        manager = GameTurnManager(None, SESSION, SimpleNamespace())
        chunks = await collect(manager.process_turn("Continue"))
        assert len(chunks) == 1 and chunks[0].startswith("event: error")
        assert '"retryable": true' in chunks[0]
    finally:
        resume.set()
        response = await asyncio.wait_for(request, timeout=2)
    assert response.status_code == 200
    assert SESSION not in _active_sessions


@pytest.mark.asyncio
async def test_busy_foreign_session_still_returns_not_found(auth_client, vn_world):
    with session_write_lease("other-session"):
        response = await auth_client.patch(
            "/api/adventures/other-session/vn-settings", json={"pace": "brisk"}
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_guard_releases_on_stream_close_and_does_not_block_other_sessions():
    closed = asyncio.Event()

    @guard_session_turn
    async def stream(_manager):
        try:
            yield "event: status\ndata: {}\n\n"
        finally:
            closed.set()

    manager = SimpleNamespace(game_id="first")
    pending = stream(manager)
    await anext(pending)
    assert "first" in _active_sessions
    assert await collect(stream(SimpleNamespace(game_id="second")))
    closed.clear()
    await pending.aclose()
    assert closed.is_set()
    assert not _active_sessions


@pytest.mark.asyncio
async def test_guard_releases_on_cancellation():
    entered, closed = asyncio.Event(), asyncio.Event()

    @guard_session_turn
    async def stream(_manager):
        entered.set()
        try:
            await asyncio.Event().wait()
            yield "unreachable"
        finally:
            closed.set()

    task = asyncio.create_task(collect(stream(SimpleNamespace(game_id="cancel"))))
    await asyncio.wait_for(entered.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()
    assert not _active_sessions


@pytest.mark.asyncio
async def test_guard_releases_on_exception():
    @guard_session_turn
    async def stream(_manager):
        raise ValueError("Failed turn")
        yield "unreachable"

    with pytest.raises(ValueError, match="Failed turn"):
        await collect(stream(SimpleNamespace(game_id="failed")))
    assert not _active_sessions
