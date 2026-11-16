"""The agent cannot mutate a session outside the foreground writer lease."""

import asyncio
from contextlib import aclosing
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.api.routes.adventures import agent_turn_stream as agent
from backend.engine.gameplay.agent_actions import AgentActionOutcome
from backend.engine.gameplay.agent_logic import AgentDecision, AgentService
from backend.engine.visual_novel.concurrency import (
    SessionBusyError,
    _active_sessions,
    guard_session_turn,
    session_write_lease,
)
from backend.models.session_state import SessionState
from backend.models.user import User
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]
GAME = "portrait-session"


async def activate():
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == GAME))
        user = await db.scalar(select(User).where(User.username == "test_user"))
        AgentService.set_agent_active(state, True)
        await db.commit()
        return user


@pytest.mark.parametrize("direct", [False, True], ids=["delegated-turn", "direct-action"])
async def test_every_agent_phase_holds_the_same_lease(
    auth_client, portrait_world, monkeypatch, direct
):
    await activate()
    phases = []
    ownership = []

    async def check(phase):
        phases.append(phase)
        ownership.append(_active_sessions[GAME])
        # The route-level conflict is covered separately. This test probes each
        # phase without opening a second transaction on the shared SQLite fixture.
        with pytest.raises(SessionBusyError), session_write_lease(GAME):
            pass
        assert agent.scheduler.active_turns > 0

    async def decide(*_args):
        await check("decision")
        return AgentDecision(
            thoughts="Inspect the room",
            action="inspect room",
            is_stuck_or_bug=False,
            issue_description="",
        ), False

    async def execute(*_args):
        await check("action")
        return (
            AgentActionOutcome(message="Opened.")
            if direct
            else AgentActionOutcome(turn_command="inspect room")
        )

    @guard_session_turn
    async def process(manager, command, *, session_lease):
        assert command == "inspect room"
        assert session_lease is ownership[0]
        await check("narration")
        yield "event: final\ndata: {}\n\n"

    async def final(*_args):
        await check("final")
        return "event: final\ndata: {}\n\n"

    async def finish(*_args):
        await check("finish")
        yield "event: agent_state\ndata: {}\n\n"

    monkeypatch.setattr(agent, "_decide", decide)
    monkeypatch.setattr(agent, "execute_agent_action", execute)
    monkeypatch.setattr(agent.GameTurnManager, "process_turn", process)
    monkeypatch.setattr(agent, "_final_event", final)
    monkeypatch.setattr(agent, "_agent_finish_events", finish)
    response = await auth_client.post(f"/api/adventures/{GAME}/agent/turn")
    assert response.status_code == 200
    assert "event: error" not in response.text
    assert phases == (
        ["decision", "action", "final"] if direct else ["decision", "action", "narration", "finish"]
    )
    assert all(lease is ownership[0] for lease in ownership)
    assert GAME not in _active_sessions


@pytest.mark.parametrize("through_route", [False, True], ids=["generator", "http-response"])
async def test_cancelled_agent_decision_releases_the_lease(
    auth_client, portrait_world, monkeypatch, through_route
):
    user = await activate()
    deciding = asyncio.Event()

    async def decide(*_args):
        deciding.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(agent, "_decide", decide)

    async def consume():
        if through_route:
            await auth_client.post(f"/api/adventures/{GAME}/agent/turn")
            return
        async with aclosing(agent.stream_agent_turn(GAME, user)) as stream:
            async for _event in stream:
                pass

    task = asyncio.create_task(consume())
    try:
        await asyncio.wait_for(deciding.wait(), timeout=2)
        with pytest.raises(SessionBusyError), session_write_lease(GAME):
            pass
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert GAME not in _active_sessions


async def test_inactive_agent_releases_preflight_lease(auth_client, portrait_world, monkeypatch):
    decision = AsyncMock()
    monkeypatch.setattr(agent, "_decide", decision)
    response = await auth_client.post(f"/api/adventures/{GAME}/agent/turn")
    assert response.status_code == 400
    decision.assert_not_awaited()
    assert GAME not in _active_sessions
