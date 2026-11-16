"""Real playtime is independent of the story clock and excludes offline gaps."""

import pytest
from sqlalchemy import select

from backend.api.routes.adventures import session_playtime
from backend.engine.visual_novel.concurrency import session_write_lease
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]
PATH = "/api/adventures/sessions/portrait-session/playtime"


@pytest.mark.parametrize(
    ("previous", "now", "start", "expected"),
    [
        (None, 100, False, 0),
        (100, 115, False, 15),
        (100, 115, True, 0),
        (100, 500, False, 0),
        (100, 99, False, 0),
        (100, 100, False, 0),
    ],
)
def test_elapsed_playtime(previous, now, start, expected):
    assert session_playtime.elapsed_playtime(previous, now, start=start) == expected


async def test_playtime_counts_visible_intervals_and_is_returned_in_library(
    auth_client, portrait_world, monkeypatch
):
    clock = [100]
    monkeypatch.setattr(session_playtime.time, "time", lambda: clock[0])
    async with TestSessionLocal() as db:
        before = await db.get(GameSession, "portrait-session")
        updated_at = before.updated_at
    for now, payload in [
        (100, {"start": True}),
        (115, {}),
        (130, {}),
        (135, {"active": False}),
        (1000, {"start": True}),
        (1015, {}),
    ]:
        clock[0] = now
        response = await auth_client.post(PATH, json=payload)
        assert response.status_code == 200, response.text
    async with TestSessionLocal() as db:
        session = await db.get(GameSession, "portrait-session")
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        assert session.playtime_seconds == 50
        assert session.updated_at == updated_at
        assert state.in_game_time == 480
    response = await auth_client.get("/api/adventures/sessions")
    assert response.status_code == 200, response.text
    saved = next(item for item in response.json() if item["game_id"] == "portrait-session")
    assert saved["playtime_seconds"] == 50
    assert saved["in_game_time"] == 480


async def test_offline_gap_is_discarded_and_duplicate_tick_does_not_double_count(
    auth_client, portrait_world, monkeypatch
):
    clock = [100]
    monkeypatch.setattr(session_playtime.time, "time", lambda: clock[0])
    for now in [100, 115, 115, 1000, 1015]:
        clock[0] = now
        assert (await auth_client.post(PATH, json={})).status_code == 200
    async with TestSessionLocal() as db:
        assert (await db.get(GameSession, "portrait-session")).playtime_seconds == 30


async def test_playtime_can_update_while_narration_is_generating(auth_client, portrait_world):
    with session_write_lease("portrait-session"):
        response = await auth_client.post(PATH, json={"start": True})
    assert response.status_code == 200


async def test_playtime_cannot_update_another_users_session(auth_client, portrait_world):
    response = await auth_client.post("/api/adventures/sessions/other-session/playtime", json={})
    assert response.status_code == 404
