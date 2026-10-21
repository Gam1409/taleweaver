"""A generated world must initialize its first session in an existing scene."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.session_start import ensure_generated_session_scene
from backend.engine.world_generator import WorldGenerator
from backend.models.adventure_template import AdventureTemplate
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldScene


@pytest.mark.asyncio
@pytest.mark.parametrize("scene_id", ["START", "VILLAGE_SQUARE"])
async def test_generated_world_materializes_a_valid_start(auth_client, monkeypatch, scene_id):
    from tests.conftest import TestSessionLocal

    async def generate(db, *, template_id, **kwargs):
        template = await db.get(AdventureTemplate, template_id)
        template.original_manifest = {"scenes": [{"id": scene_id}], "quests": []}
        db.add(
            WorldScene(
                id=scene_id,
                template_id=template_id,
                label="Village",
                description="A peaceful village.",
            )
        )
        await db.commit()

    monkeypatch.setattr(WorldGenerator, "generate_world", generate)
    response = await auth_client.post(
        "/api/adventures/", json={"title": "Valid Initial Scene", "auto_validate_and_fix": False}
    )
    assert response.status_code == 201
    game_id = response.json()["game_id"]
    async with TestSessionLocal() as db:
        state = (
            await db.execute(select(SessionState).where(SessionState.session_id == game_id))
        ).scalar_one()
        assert state.current_scene_id == scene_id
        scene = (
            await db.execute(
                select(WorldScene).where(
                    WorldScene.session_id == game_id, WorldScene.id == state.current_scene_id
                )
            )
        ).scalar_one_or_none()
        assert scene is not None


@pytest.mark.asyncio
async def test_existing_valid_session_location_is_preserved():
    from unittest.mock import AsyncMock, MagicMock

    result = MagicMock()
    result.scalars.return_value.all.return_value = ["VILLAGE", "FOREST"]
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    state = SimpleNamespace(session_id="test-session", current_scene_id="FOREST")
    await ensure_generated_session_scene(db, "test-template", state)
    assert state.current_scene_id == "FOREST"
    db.execute.assert_awaited_once()
