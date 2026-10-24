"""Display titles must never become newly allocated storage identifiers."""

from uuid import UUID

import pytest
from sqlalchemy import select

from backend.core.config import settings
from backend.engine.adventure_cloner import generate_cloned_adventure_id
from backend.engine.world_generator import WorldGenerator
from backend.models.adventure_template import AdventureTemplate
from backend.models.game_session import GameSession
from backend.models.world_entity import WorldScene
from backend.utils.text_utils import generate_adventure_id, generate_session_id
from tests.conftest import TestSessionLocal


@pytest.mark.parametrize(
    "factory", [generate_adventure_id, generate_session_id, generate_cloned_adventure_id]
)
@pytest.mark.parametrize(
    "title", ["Одинокий путник", "森", "رحلة", "El bosque mágico", "😀", "../title", "a" * 500, ""]
)
def test_storage_ids_are_uuid_independent_of_title(factory, title):
    first, second = factory(title), factory(title)
    assert UUID(first).version == UUID(second).version == 7
    assert first.isascii() and second.isascii()
    assert len(first) == len(second) == 36
    assert first != second


async def test_create_start_and_copy_use_uuid_without_changing_title(
    auth_client, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    title = "Одинокий путник — 森 🌲"

    async def generate(db, *, template_id, **kwargs):
        template = await db.get(AdventureTemplate, template_id)
        template.sequences = [{"id": "SEQ_1", "title": "Начало", "scenes": ["FOREST"]}]
        template.original_manifest = {"scenes": [{"id": "FOREST"}], "quests": []}
        db.add(
            WorldScene(id="FOREST", template_id=template_id, label="Лес", description="Тихий лес.")
        )
        await db.commit()

    monkeypatch.setattr(WorldGenerator, "generate_world", generate)
    created = await auth_client.post(
        "/api/adventures/", json={"title": title, "auto_validate_and_fix": False}
    )
    assert created.status_code == 201, created.text
    template_id, first_id = created.json()["adventure_id"], created.json()["game_id"]
    started = await auth_client.post(f"/api/adventures/{template_id}/sessions/start")
    assert started.status_code == 201, started.text
    second_id = started.json()["game_id"]
    copied = await auth_client.post(f"/api/adventures/sessions/{second_id}/copy")
    assert copied.status_code == 201, copied.text
    copy_id = copied.json()["game_id"]
    assert len({template_id, first_id, second_id, copy_id}) == 4
    assert all(UUID(value).version == 7 for value in (template_id, first_id, second_id, copy_id))
    async with TestSessionLocal() as db:
        template = await db.get(AdventureTemplate, template_id)
        assert template.title == title
        sessions = (await db.execute(select(GameSession))).scalars().all()
        assert {s.id for s in sessions} == {first_id, second_id, copy_id}
        assert all(title in s.adventure_title for s in sessions)
    for session_id in (first_id, second_id, copy_id):
        response = await auth_client.get(f"/api/adventures/sessions/{session_id}/export")
        assert response.status_code == 200, response.text[:200]
