"""Existing roster selections do not block budget changes after an NPC leaves view."""

from sqlalchemy import select

from backend.engine.chpm.schema import KernelState, Settings
from backend.engine.chpm.state import KEY
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_chpm_api import chpm_world
from tests.test_session_portraits import portrait_world

__all__ = ["chpm_world", "portrait_world"]
PATH = "/api/adventures/portrait-session/chpm"


async def test_budget_change_retains_saved_unlisted_actor_but_cannot_add_an_unknown_npc(
    auth_client, chpm_world
):
    settings = Settings(mode="live", actor_ids=["NPC_NEW", "AWAY"])
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        state.entity_states = {
            **state.entity_states,
            KEY: KernelState(settings=settings).model_dump(),
        }
        db.add_all(
            [
                WorldEntity(
                    id=identifier,
                    name=name,
                    description="An off-scene character.",
                    entity_type="NPC",
                    template_id="portrait-template",
                    session_id="portrait-session",
                    current_scene_id="OFF_SCENE",
                    is_hidden=True,
                    metadata_json={},
                )
                for identifier, name in (
                    ("AWAY", "PRIVATE_SAVED_NAME"),
                    ("UNKNOWN", "PRIVATE_UNKNOWN_NAME"),
                )
            ]
        )
        await db.commit()
    view = await auth_client.get(PATH)
    assert view.status_code == 200, view.text
    assert view.json()["settings"]["actor_ids"] == ["NPC_NEW", "AWAY"]
    assert "PRIVATE_SAVED_NAME" not in view.text and "PRIVATE_UNKNOWN_NAME" not in view.text
    changed = settings.model_copy(update={"max_input_chars": 48000})
    result = await auth_client.patch(
        PATH, json={"expected_revision": 0, "settings": changed.model_dump()}
    )
    assert result.status_code == 200, result.text
    assert result.json()["settings"]["actor_ids"] == settings.actor_ids
    unknown = changed.model_copy(update={"actor_ids": ["NPC_NEW", "AWAY", "UNKNOWN"]})
    result = await auth_client.patch(
        PATH, json={"expected_revision": 1, "settings": unknown.model_dump()}
    )
    assert result.status_code == 422
    assert "UNKNOWN" in result.json()["detail"]
    assert "PRIVATE_UNKNOWN_NAME" not in result.text
