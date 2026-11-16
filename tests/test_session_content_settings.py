"""Changing session preferences preserves gameplay, ownership and replay state."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import Text, cast, select, update

from backend.engine.session_content_settings import (
    SNAPSHOT_KEY,
    ContentPreferencesUpdate,
    ContentSettingsConflictError,
    read_preferences,
    save_preferences,
)
from backend.engine.session_portraits import _settings
from backend.engine.turn_replay import service
from backend.engine.turn_replay.snapshot import capture
from backend.engine.visual_novel import narration
from backend.engine.visual_novel.concurrency import session_write_lease
from backend.models.adventure_template import AdventureTemplate
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from backend.models.turn_replay import TurnReplay
from backend.models.user import User
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]
PATH = "/api/adventures/portrait-session/content-settings"
OFF = {"enabled": False, "level": "soft"}


@pytest.fixture
async def content_world(portrait_world):
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        state.entity_states = {
            **state.entity_states,
            SNAPSHOT_KEY: {
                "adventure": {"title": "Saved title"},
                "original_manifest": {
                    "nsfw_settings": OFF,
                    "clothing_settings": {"detailed": False},
                    "plot": "Saved plot",
                },
            },
        }
        db.add(
            ChatMessage(
                session_id="portrait-session", role="assistant", content="Original response."
            )
        )
        await db.commit()


@pytest.mark.parametrize("level", ["soft", "medium", "hard"])
async def test_update_and_disable_preserve_progress_and_template(
    auth_client, content_world, level, monkeypatch
):
    async with TestSessionLocal() as db:
        before = dict(
            (
                await db.execute(
                    select(SessionState.__table__).where(
                        SessionState.session_id == "portrait-session"
                    )
                )
            )
            .mappings()
            .one()
        )
        template_before = deepcopy(
            (await db.get(AdventureTemplate, "portrait-template")).original_manifest
        )
    response = await auth_client.get(PATH)
    assert response.json() == OFF
    enabled = {"enabled": True, "level": level}
    response = await auth_client.patch(PATH, json={"settings": enabled, "expected": OFF})
    assert response.status_code == 200, response.text
    assert (await auth_client.get(PATH)).json() == enabled
    monkeypatch.setattr(
        narration.mature_content_prompts, "narrative_addendum", lambda value: f"TEST_MARKER_{value}"
    )
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        after = dict(
            (await db.execute(select(SessionState.__table__).where(SessionState.id == state.id)))
            .mappings()
            .one()
        )
        assert "TEST_MARKER_" + level in narration.narration_suffix(state)
        user = await db.scalar(select(User))
        image_options, _, _ = await _settings(db, state, user)
        assert image_options["_nsfw_enabled"] is True
        assert image_options["_nsfw_level"] == level
        expected_states = deepcopy(before["entity_states"])
        expected_states[SNAPSHOT_KEY]["original_manifest"]["nsfw_settings"] = enabled
        assert after.pop("entity_states") == expected_states
        before.pop("entity_states")
        after.pop("updated_at", None)
        before.pop("updated_at", None)
        assert before == after
        assert (
            await db.get(AdventureTemplate, "portrait-template")
        ).original_manifest == template_before
        assert (await db.scalar(select(ChatMessage))).content == "Original response."
    disabled = {"enabled": False, "level": level}
    response = await auth_client.patch(PATH, json={"settings": disabled, "expected": enabled})
    assert response.json() == disabled
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        assert "TEST_MARKER_" not in narration.narration_suffix(state)


async def test_busy_stale_and_foreign_requests_are_rejected(auth_client, content_world):
    payload = {"settings": {"enabled": True, "level": "medium"}, "expected": OFF}
    with session_write_lease("portrait-session"):
        assert (await auth_client.patch(PATH, json=payload)).status_code == 409
    assert (await auth_client.patch(PATH, json=payload)).status_code == 200
    assert (await auth_client.patch(PATH, json=payload)).status_code == 409
    for method in (auth_client.get, auth_client.patch):
        kwargs = {"json": payload} if method == auth_client.patch else {}
        response = await method(PATH.replace("portrait-session", "other-session"), **kwargs)
        assert response.status_code == 404


async def test_replay_uses_new_preferences_without_changing_rewound_game_state(
    auth_client, content_world
):
    async with TestSessionLocal() as db:
        before = await capture(db, "portrait-session")
        message = await db.scalar(select(ChatMessage))
        message_id = message.id
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
    preferences = {"enabled": True, "level": "medium"}
    response = await auth_client.patch(PATH, json={"settings": preferences, "expected": OFF})
    assert response.status_code == 200, response.text
    async with TestSessionLocal() as db:
        user = await db.scalar(select(User))
        manager = SimpleNamespace(db=db, game_id="portrait-session", user=user)
        await service.begin(manager, message_id)
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        assert state.in_game_time == 480
        assert read_preferences(state.entity_states).model_dump() == preferences
        await service.recover(db, "portrait-session")
        await db.refresh(state)
        assert state.in_game_time == 600
        assert read_preferences(state.entity_states).model_dump() == preferences


async def test_stale_json_does_not_erase_other_changes(content_world):
    async with TestSessionLocal() as db:
        state, raw = (
            await db.execute(
                select(
                    SessionState, cast(SessionState.entity_states, Text).label("state_json")
                ).where(SessionState.session_id == "portrait-session")
            )
        ).one()
        changed = {**state.entity_states, "new_fact": "keep"}
        await db.execute(
            update(SessionState)
            .where(SessionState.id == state.id)
            .values(entity_states=changed)
            .execution_options(synchronize_session=False)
        )
        await db.commit()
        payload = ContentPreferencesUpdate(
            settings={"enabled": True, "level": "soft"}, expected=OFF
        )
        with pytest.raises(ContentSettingsConflictError):
            await save_preferences(db, state, raw, payload)
        await db.rollback()
        await db.refresh(state)
        assert state.entity_states["new_fact"] == "keep"
        assert read_preferences(state.entity_states).model_dump() == OFF


@pytest.mark.parametrize(
    "settings",
    [
        {"enabled": "yes", "level": "soft"},
        {"enabled": True, "level": "unknown"},
        {"enabled": True, "level": "soft", "plot": "replace"},
    ],
)
async def test_invalid_preferences_are_rejected(auth_client, content_world, settings):
    response = await auth_client.patch(PATH, json={"settings": settings, "expected": OFF})
    assert response.status_code == 422
    assert (await auth_client.get(PATH)).json() == OFF


async def test_missing_manifest_is_not_rebuilt_from_current_template(auth_client, content_world):
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        state.entity_states = {"NPC_NEW": {"hp": 17}}
        await db.commit()
    assert (await auth_client.get(PATH)).status_code == 409
    response = await auth_client.patch(
        PATH, json={"settings": {"enabled": True, "level": "soft"}, "expected": OFF}
    )
    assert response.status_code == 409
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        assert state.entity_states == {"NPC_NEW": {"hp": 17}}


async def test_interrupted_replay_requires_recovery_before_edit(auth_client, content_world):
    async with TestSessionLocal() as db:
        snapshot = await capture(db, "portrait-session")
        db.add(
            TurnReplay(
                session_id="portrait-session",
                before=snapshot,
                backup=snapshot,
                input_text="Hi",
                status="replaying",
            )
        )
        await db.commit()
    response = await auth_client.patch(
        PATH, json={"settings": {"enabled": True, "level": "soft"}, "expected": OFF}
    )
    assert response.status_code == 409
    assert (await auth_client.get(PATH)).json() == OFF
