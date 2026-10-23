"""Portraits for IDs produced from real multilingual adventure titles."""

import io
import zipfile
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

from backend.api.routes.adventures.logic import AdventureLogic
from backend.core.config import settings
from backend.engine.media_engine import MediaEngine
from backend.engine.session_exporter import SessionExporter
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.models.world_entity import WorldEntity
from backend.utils.path_security import data_url_to_local_path
from backend.utils.text_utils import generate_session_id
from tests.conftest import TestSessionLocal
from tests.test_comfyui import comfy_options, fake_comfy, workflow
from tests.test_session_portraits import finish_job, portrait_world, start_job

__all__ = ["comfy_options", "fake_comfy", "portrait_world", "workflow"]
REAL_GENERATE_IMAGE = MediaEngine.generate_image


async def seed_localized_session(
    title: str, image_url: str | None = "/data/old-portrait.png"
) -> str:
    session_id = generate_session_id(title)
    async with TestSessionLocal() as db:
        original = await db.get(GameSession, "portrait-session")
        db.add(
            GameSession(
                id=session_id,
                user_id=original.user_id,
                avatar_id=original.avatar_id,
                template_id=original.template_id,
                adventure_title=title,
            )
        )
        db.add(
            SessionState(
                session_id=session_id,
                current_scene_id="FOREST",
                in_game_time=520,
                quests=[{"id": "escape", "status": "active"}],
            )
        )
        db.add(
            WorldEntity(
                id="NPC_THIEF",
                session_id=session_id,
                entity_type="NPC",
                name="Вор",
                description="A thief in a dark cloak",
                current_scene_id="FOREST",
                image_url=image_url,
            )
        )
        await db.commit()
    return session_id


@pytest.mark.parametrize(
    "title", ["Бегство из леса", "森からの脱出", "رحلة الغابة", "El bosque mágico"]
)
@pytest.mark.parametrize("old_image", [None, "/data/old-portrait.png"])
async def test_localized_save_can_regenerate_reload_and_export(
    auth_client, portrait_world, title, old_image
):
    session_id = await seed_localized_session(title, old_image)
    job = await start_job(auth_client, session_id, "NPC_THIEF")
    result = await finish_job(auth_client, job)

    assert result["state"] == "succeeded", result
    assert len(portrait_world) == 1
    image_url = result["result"]["image_url"]
    assert image_url.startswith(f"/data/adventures/sessions/{session_id}/visuals/entities/")
    local_path = data_url_to_local_path(image_url)
    assert local_path and Path(local_path).is_file()
    async with TestSessionLocal() as db:
        state = (
            await db.execute(select(SessionState).where(SessionState.session_id == session_id))
        ).scalar_one()
        entities = await AdventureLogic.build_session_entities(db, state)
        assert entities[0]["image_url"] == image_url
        assert state.in_game_time == 520
        assert state.quests == [{"id": "escape", "status": "active"}]
        archive = await SessionExporter.export_ads(db, session_id)
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        assert f"assets/visuals/entities/{Path(local_path).name}" in bundle.namelist()


async def test_foreign_localized_save_is_still_inaccessible(auth_client, portrait_world):
    session_id = await seed_localized_session("Чужое приключение")
    async with TestSessionLocal() as db:
        session = await db.get(GameSession, session_id)
        session.user_id = "another-owner"
        await db.commit()

    result = await finish_job(auth_client, await start_job(auth_client, session_id, "NPC_THIEF"))
    assert result["state"] == "failed"
    assert result["message"] == "Session not found."
    assert portrait_world == []


async def test_missing_portrait_comfy_pipeline_writes_and_serves_unicode_path(
    auth_client, portrait_world, fake_comfy, comfy_options, monkeypatch
):
    """Exercise the real image adapter/writer; only ComfyUI HTTP is faked."""
    session_id = await seed_localized_session("Бегство из леса", image_url=None)
    async with TestSessionLocal() as db:
        user = (await db.execute(select(User))).scalars().first()
        user.t2i_settings = {**comfy_options, "profile_model_quality": "simple"}
        await db.commit()
    monkeypatch.setattr(MediaEngine, "generate_image", REAL_GENERATE_IMAGE)

    result = await finish_job(auth_client, await start_job(auth_client, session_id, "NPC_THIEF"))

    assert result["state"] == "succeeded", result
    assert sum(request.url.path == "/prompt" for request in fake_comfy) == 1
    assert not any(request.url.path == "/upload/image" for request in fake_comfy)
    image_url = result["result"]["image_url"]
    image = Path(data_url_to_local_path(image_url))
    thumbnail = image.with_stem(f"{image.stem}_thumb")
    assert image.is_file() and thumbnail.is_file()
    app = Starlette(routes=[Mount("/data", StaticFiles(directory=settings.DATA_DIR))])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as media:
        response = await media.get(image_url)
    assert response.status_code == 200
    assert response.content == image.read_bytes()
