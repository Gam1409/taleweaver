"""Paired execution experiment: change the scene courtesy rule, hold the choice fixed."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from backend.engine.living_world.state import load, public_status
from backend.models import ChatMessage, SessionState
from tests import test_living_world_decisions as helpers
from tests.conftest import TestSessionLocal

ready, world = helpers.ready, helpers.world


@pytest.mark.parametrize("allow", [False, True])
async def test_decided_departure_during_dialogue(ready, monkeypatch, allow):
    await helpers.configure(
        ready, deliberation_enabled=True, mode="CATCH_UP", allow_decided_moves_during_dialogue=allow
    )
    async with TestSessionLocal() as db:
        db.add(
            ChatMessage(
                id="recent",
                session_id="session-1",
                role="assistant",
                scene_id="START",
                content="The conversation continues.",
                created_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
    requests = helpers.fake(monkeypatch, action="MOVE", destination="ROOM")
    response = await helpers.post(ready)
    assert response.status_code == 200, response.text
    assert len(requests) == 1
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "session-1"))
        sim = load(state)
        event = sim.events[0]
        assert event.status == ("COMMITTED" if allow else "DEFERRED")
        assert event.observed_by_player
        assert event.deferrals == (0 if allow else 1)
        position = (state.entity_states or {}).get("LILI", {}).get("current_scene_id", "START")
        assert position == ("ROOM" if allow else "START")
        if allow:
            assert public_status(sim)["recap"] == [event.result]
            assert sim.private_notes["LILI"].goal == "Find a quiet place."
