"""Creation IDs retain the distinct immediate-session and generated-template contracts."""

import pytest
from sqlalchemy import select

from backend.engine.template_avatar import get_template_avatar
from backend.models.avatar import Avatar
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("skip_generation", [True, False])
async def test_create_response_avatar_targets_the_existing_branch_contract(
    auth_client, skip_generation
):
    response = await auth_client.post(
        "/api/adventures/",
        json={
            "title": "Creation avatar contract",
            "avatar_name": "Archive keeper",
            "skip_generation": skip_generation,
        },
    )
    assert response.status_code == 201, response.text
    identifiers = response.json()
    async with TestSessionLocal() as db:
        game = await db.get(GameSession, identifiers["game_id"])
        state = await db.scalar(select(SessionState).where(SessionState.session_id == game.id))
        blueprint = await get_template_avatar(db, identifiers["adventure_id"])
        assert blueprint is not None
        assert game.avatar_id != blueprint.id
        assert state.avatar_id == game.avatar_id
        assert identifiers["avatar_id"] == (game.avatar_id if skip_generation else blueprint.id)

    changed = await auth_client.patch(
        f"/api/avatars/{identifiers['avatar_id']}",
        json={
            "hp": 123,
            "inventory": [{"id": "BRASS_KEY", "name": "Brass key", "item_type": "KEY"}],
        },
    )
    assert changed.status_code == 200, changed.text
    async with TestSessionLocal() as db:
        game = await db.get(GameSession, identifiers["game_id"])
        saved = await db.get(Avatar, game.avatar_id)
        blueprint = await get_template_avatar(db, identifiers["adventure_id"])
        assert saved.hp == (123 if skip_generation else 200)
        assert blueprint.hp == (200 if skip_generation else 123)
        assert saved.inventory == (changed.json()["inventory"] if skip_generation else [])
        assert blueprint.inventory == ([] if skip_generation else changed.json()["inventory"])

    editor = await auth_client.get(f"/api/adventures/{identifiers['adventure_id']}/editor/assets")
    assert editor.status_code == 200, editor.text
    assert editor.json()["protagonist"]["hp"] == (200 if skip_generation else 123)


async def test_skip_generation_response_avatar_inventory_is_used_by_gameplay(auth_client):
    response = await auth_client.post(
        "/api/adventures/",
        json={"title": "Immediate session", "avatar_name": "Keeper", "skip_generation": True},
    )
    assert response.status_code == 201, response.text
    identifiers = response.json()
    changed = await auth_client.patch(
        f"/api/avatars/{identifiers['avatar_id']}",
        json={"inventory": [{"id": "BRASS_KEY", "name": "Brass key", "item_type": "KEY"}]},
    )
    assert changed.status_code == 200, changed.text
    async with TestSessionLocal() as db:
        db.add(
            WorldEntity(
                id="CHEST",
                session_id=identifiers["game_id"],
                entity_type="OBJECT",
                item_type="CONTAINER",
                name="Chest",
                description="A locked chest.",
                current_scene_id="START",
                metadata_json={"item_to_unlock": "BRASS_KEY", "locked": True},
            )
        )
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == identifiers["game_id"])
        )
        state.entity_states = {**(state.entity_states or {}), "CHEST": {"locked": True}}
        await db.commit()

    unlocked = await auth_client.post(
        f"/api/adventures/{identifiers['game_id']}/containers/CHEST/unlock-item",
        json={"item_id": "BRASS_KEY"},
    )
    assert unlocked.status_code == 200, unlocked.text
    assert unlocked.json()["locked"] is False
