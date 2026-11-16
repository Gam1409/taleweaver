"""Session ownership, optimistic saves and replay preserve opt-ins independently."""

from types import SimpleNamespace

import pytest
from sqlalchemy import Text, cast, select, update

from backend.core.npc_presentation import PortraitPreferences, PreferencesUpdate
from backend.engine.npc_presentation.settings import KEY, PreferencesConflictError, read, save
from backend.engine.turn_replay import service
from backend.engine.turn_replay.snapshot import capture
from backend.engine.visual_novel.concurrency import session_write_lease
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from backend.models.turn_replay import TurnReplay
from backend.models.user import User
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]
PATH = "/api/adventures/portrait-session/portrait-settings"
OFF = PortraitPreferences().model_dump()
ON = {**OFF, "emotion_palette": True, "character_thoughts": True, "brightness": 55}


async def test_owned_opt_ins_persist_without_changing_other_state(auth_client, portrait_world):
    assert (await auth_client.get(PATH)).json() == OFF
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        previous = state.entity_states
    response = await auth_client.patch(PATH, json={"settings": ON, "expected": OFF})
    assert response.status_code == 200, response.text
    assert response.json() == ON
    assert (await auth_client.get(PATH)).json() == ON
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        assert state.entity_states == {**previous, KEY: ON}
        assert state.in_game_time == 480
    assert (
        await auth_client.get(PATH.replace("portrait-session", "other-session"))
    ).status_code == 404
    assert (
        await auth_client.patch(
            PATH.replace("portrait-session", "other-session"),
            json={"settings": ON, "expected": OFF},
        )
    ).status_code == 404
    assert (
        await auth_client.patch(PATH, json={"settings": ON, "expected": OFF})
    ).status_code == 409
    with session_write_lease("portrait-session"):
        assert (
            await auth_client.patch(PATH, json={"settings": OFF, "expected": ON})
        ).status_code == 409
    assert (await auth_client.patch(PATH, json={"settings": OFF, "expected": ON})).json() == OFF


@pytest.mark.parametrize(
    "invalid",
    [
        {"emotion_palette": "true"},
        {"character_thoughts": 1},
        {"brightness": -1},
        {"brightness": 101},
        {"brightness": 3.5},
        {"brightness": True},
        {"other": True},
    ],
)
async def test_invalid_settings_rejected_before_overwriting(auth_client, portrait_world, invalid):
    response = await auth_client.patch(PATH, json={"settings": {**ON, **invalid}, "expected": OFF})
    assert response.status_code == 422
    assert (await auth_client.get(PATH)).json() == OFF


async def test_replay_keeps_preferences_and_existing_message_metadata(auth_client, portrait_world):
    async with TestSessionLocal() as db:
        message = ChatMessage(session_id="portrait-session", role="assistant", content="Original")
        db.add(message)
        await db.flush()
        message_id = message.id
        before = await capture(db, "portrait-session")
        db.add(
            TurnReplay(
                session_id="portrait-session",
                before=before,
                input_text="Hello",
                assistant_id=message_id,
                status="ready",
            )
        )
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        state.in_game_time = 600
        await db.commit()
    assert (
        await auth_client.patch(PATH, json={"settings": ON, "expected": OFF})
    ).status_code == 200
    async with TestSessionLocal() as db:
        manager = SimpleNamespace(
            db=db, game_id="portrait-session", user=await db.scalar(select(User))
        )
        await service.begin(manager, message_id)
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        assert state.in_game_time == 480
        assert read(state.entity_states).model_dump() == ON
        await service.recover(db, "portrait-session")
        await db.refresh(state)
        assert state.in_game_time == 600
        assert read(state.entity_states).model_dump() == ON


async def test_compare_and_swap_keeps_concurrent_gameplay_changes(portrait_world):
    async with TestSessionLocal() as db:
        state, raw = (
            await db.execute(
                select(
                    SessionState, cast(SessionState.entity_states, Text).label("state_json")
                ).where(SessionState.session_id == "portrait-session")
            )
        ).one()
        await db.execute(
            update(SessionState)
            .where(SessionState.id == state.id)
            .values(entity_states={**state.entity_states, "NEW_FACT": True})
            .execution_options(synchronize_session=False)
        )
        with pytest.raises(PreferencesConflictError):
            await save(
                db,
                state,
                raw,
                PreferencesUpdate(
                    settings=PortraitPreferences(**ON), expected=PortraitPreferences()
                ),
            )
        await db.refresh(state)
        assert state.entity_states["NEW_FACT"] is True
        assert KEY not in state.entity_states
