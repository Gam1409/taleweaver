"""Delegated turns reuse only an explicit, currently active writer capability."""

import asyncio
from contextlib import aclosing
from types import SimpleNamespace

import pytest

from backend.engine.visual_novel.concurrency import (
    SessionBusyError,
    SessionLease,
    guard_session_turn,
    session_write_lease,
)


@guard_session_turn
async def turn(manager, *, session_lease=None):
    with pytest.raises(SessionBusyError), session_write_lease(manager.game_id):
        pass
    yield "owned"


async def test_explicit_delegation_does_not_release_its_owner():
    manager = SimpleNamespace(game_id="delegated")
    with session_write_lease(manager.game_id) as lease:
        assert [event async for event in turn(manager, session_lease=lease)] == ["owned"]
        with pytest.raises(SessionBusyError), session_write_lease(manager.game_id):
            pass
    with session_write_lease(manager.game_id):
        pass


async def test_child_tasks_do_not_implicitly_inherit_writer_access():
    manager = SimpleNamespace(game_id="delegated")

    async def child():
        return [event async for event in turn(manager)]

    with session_write_lease(manager.game_id):
        result = await asyncio.create_task(child())
    assert len(result) == 1
    assert "event: error" in result[0]
    assert '"retryable": true' in result[0]


@pytest.mark.parametrize("invalid", ["forged", "wrong-session", "expired"])
def test_only_the_active_identity_can_be_borrowed(invalid):
    with session_write_lease("previous") as expired:
        pass
    with session_write_lease("delegated") as owner:
        candidate = {
            "forged": SessionLease("delegated"),
            "wrong-session": owner,
            "expired": expired,
        }[invalid]
        target = "other" if invalid == "wrong-session" else "delegated"
        with pytest.raises(SessionBusyError), session_write_lease(target, lease=candidate):
            pass
        with pytest.raises(SessionBusyError), session_write_lease("delegated"):
            pass


async def test_closing_a_borrowed_stream_keeps_the_outer_lease_active():
    manager = SimpleNamespace(game_id="delegated")
    with session_write_lease(manager.game_id) as owner:
        async with aclosing(turn(manager, session_lease=owner)) as stream:
            assert await anext(stream) == "owned"
        with pytest.raises(SessionBusyError), session_write_lease(manager.game_id):
            pass
