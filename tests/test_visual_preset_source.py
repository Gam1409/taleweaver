"""Current settings bypass saved assignments without losing the saved choice."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.engine.story_visual_presets import preserve_story_presets, story_t2i
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.test_session_content_settings import content_world, portrait_world

__all__ = ["content_world", "portrait_world"]
PATH = "/api/adventures/portrait-session/session-visual-presets"


def test_current_source_ignores_unavailable_saved_preset():
    story = SimpleNamespace(
        original_manifest={
            "visual_presets": {"advanced": "removed-preset"},
            "visual_preset_source": "current",
        }
    )
    assert (
        story_t2i({"advanced_model": "current-model"}, story)["advanced_model"] == "current-model"
    )
    assert preserve_story_presets({}, story)["visual_preset_source"] == "current"
    story.original_manifest["visual_preset_source"] = "saved"
    with pytest.raises(ValueError, match="unavailable"):
        story_t2i({}, story)


async def test_session_can_follow_current_settings_and_preserve_saved_choice(
    auth_client, content_world
):
    payload = {"source": "current", "selection": {"advanced": "removed-preset"}}
    response = await auth_client.put(PATH, json=payload)
    assert response.status_code == 200, response.text
    data = (await auth_client.get(PATH)).json()
    assert data["source"] == "current"
    assert data["selection"] == payload["selection"]
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        manifest = state.entity_states["__manifest_snapshot__"]["original_manifest"]
        assert manifest["plot"] == "Saved plot"
    response = await auth_client.put(PATH, json={**payload, "source": "saved"})
    assert response.status_code == 400
    assert (await auth_client.get(PATH)).json()["source"] == "current"


async def test_session_source_requires_ownership(auth_client, content_world):
    response = await auth_client.put(
        "/api/adventures/missing-session/session-visual-presets",
        json={"source": "current", "selection": {}},
    )
    assert response.status_code == 404


async def test_source_change_updates_replay_snapshot(auth_client, content_world):
    from copy import deepcopy

    from backend.models.turn_replay import TurnReplay

    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        db.add(
            TurnReplay(
                session_id="portrait-session",
                input_text="Hello",
                status="ready",
                before={"state": {"entity_states": deepcopy(state.entity_states)}},
            )
        )
        await db.commit()
    response = await auth_client.put(PATH, json={"source": "current", "selection": {}})
    assert response.status_code == 200, response.text
    async with TestSessionLocal() as db:
        replay = await db.scalar(
            select(TurnReplay).where(TurnReplay.session_id == "portrait-session")
        )
        manifest = replay.before["state"]["entity_states"]["__manifest_snapshot__"][
            "original_manifest"
        ]
        assert manifest["visual_preset_source"] == "current"
        assert manifest["plot"] == "Saved plot"
