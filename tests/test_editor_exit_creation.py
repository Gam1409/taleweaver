"""Exit creation must preserve every behavior field exposed by the editor."""

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.editing.exit_fields import EXIT_SCRIPT_FIELDS
from backend.models.adventure_template import AdventureTemplate
from backend.models.user import User
from backend.models.world_entity import WorldExit, WorldScene
from tests.conftest import TestSessionLocal


async def seed():
    async with TestSessionLocal() as db:
        user = (await db.execute(select(User).where(User.username == "test_user"))).scalar_one()
        adventure = AdventureTemplate(
            title="Doors", owner_id=user.id, original_manifest={"exits": []}
        )
        db.add(adventure)
        await db.flush()
        db.add_all(
            [
                WorldScene(id=scene, template_id=adventure.id, label=scene, description=scene)
                for scene in ("HALL", "YARD")
            ]
        )
        await db.commit()
        return adventure.id


@pytest.mark.parametrize("exit_type", ["one_way", "bidirectional"])
async def test_create_exit_preserves_behavior_and_manifest(auth_client, setup_test_db, exit_type):
    template_id = await seed()
    values = {
        "unlock_expression": "tw.vars.get('door_ready') == True",
        "on_open_exit_script": "tw.vars.set('opened', True)",
        "on_open_exit_text": "Дверь открывается.",
        "on_exit_used_script": "tw.vars.set('visited_yard', True)",
        "on_exit_used_text": "Вы выходите во двор.",
        "on_unlock_success_script": "tw.vars.set('unlocked', True)",
        "on_unlock_success_text": "Замок поддался.",
        "on_unlock_failure_script": "tw.vars.set('failed', True)",
        "on_unlock_failure_text": "Дверь заперта.",
    }
    assert set(values) == set(EXIT_SCRIPT_FIELDS)
    response = await auth_client.post(
        f"/api/adventures/{template_id}/editor/exit",
        json={
            "from_scene_id": "HALL",
            "to_scene_id": "YARD",
            "label": "Door",
            "exit_type": exit_type,
            "is_locked": True,
            "lock_description": "A locked door",
            **values,
        },
    )
    assert response.status_code == 200, response.text
    created = response.json()["exit"]
    assert {key: created[key] for key in values} == values
    async with TestSessionLocal() as db:
        row = await db.get(WorldExit, created["id"])
        assert {key: getattr(row, key) for key in values} == values
        adventure = await db.get(AdventureTemplate, template_id)
        manifest_exit = adventure.original_manifest["exits"][0]
        assert manifest_exit["id"] == created["id"]
        assert {key: manifest_exit[key] for key in values} == values
    # A subsequent edit must find the same manifest entry and keep other scripts.
    response = await auth_client.patch(
        f"/api/adventures/{template_id}/editor/entity",
        json={
            "target_type": "exit",
            "target_id": created["id"],
            "on_open_exit_text": "Changed",
        },
    )
    assert response.status_code == 200, response.text
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, template_id)
        assert adventure.original_manifest["exits"][0]["on_open_exit_text"] == "Changed"
        assert (
            adventure.original_manifest["exits"][0]["on_exit_used_script"]
            == values["on_exit_used_script"]
        )


async def test_create_exit_accepts_empty_optional_behavior(auth_client, setup_test_db):
    template_id = await seed()
    response = await auth_client.post(
        f"/api/adventures/{template_id}/editor/exit",
        json={
            "from_scene_id": "HALL",
            "to_scene_id": "YARD",
            "label": "Door",
            "on_open_exit_script": "  ",
            "on_open_exit_text": "  A door opens.  ",
        },
    )
    assert response.status_code == 200, response.text
    assert not response.json()["exit"]["on_open_exit_script"]
    assert response.json()["exit"]["on_open_exit_text"] == "A door opens."
