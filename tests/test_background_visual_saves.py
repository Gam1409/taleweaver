"""Completed background images survive contention but never overwrite changed sources."""

import sqlite3

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.dml import Update

from backend.engine.dynamic_locations import images
from backend.engine.media_engine import MediaEngine
from backend.engine.memory_rag import persistence
from backend.models.adventure_template import AdventureTemplate
from backend.models.user import User
from backend.models.world_entity import WorldScene
from tests.conftest import TestSessionLocal
from tests.test_dynamic_location_lifecycle import seed
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]


@pytest.mark.parametrize("change", ["edit", "image", "delete", "owner"])
async def test_template_generation_rejects_changed_source(
    auth_client, portrait_world, monkeypatch, change
):
    async def generate(**kwargs):
        async with TestSessionLocal() as db:
            adventure = await db.get(AdventureTemplate, "portrait-template")
            if change == "delete":
                await db.delete(adventure)
            elif change == "owner":
                adventure.owner_id = "other-owner"
            elif change == "image":
                adventure.image_url = "/data/newer.png"
            else:
                adventure.title = "Updated source"
            await db.commit()
        return "/data/obsolete.png"

    monkeypatch.setattr(MediaEngine, "generate_adventure_cover", generate)
    response = await auth_client.post(
        "/api/adventures/portrait-template/visuals/regenerate",
        json={"target_type": "cover", "target_id": "cover"},
    )
    assert response.status_code == (404 if change in {"delete", "owner"} else 409), response.text
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, "portrait-template")
        assert adventure is None or adventure.image_url != "/data/obsolete.png"


async def test_template_save_retries_without_regenerating(auth_client, portrait_world, monkeypatch):
    monkeypatch.setattr(persistence, "RETRY_DELAYS", (0,))
    original = AsyncSession.execute
    writes = []
    generated = []

    async def execute(db, statement, *args, **kwargs):
        if isinstance(statement, Update) and statement.table.name == "adventure_templates":
            writes.append(db)
            if len(writes) == 1:
                raise sqlite3.OperationalError("database is locked")
        return await original(db, statement, *args, **kwargs)

    async def generate(**kwargs):
        generated.append(kwargs)
        return "/data/generated.png"

    monkeypatch.setattr(AsyncSession, "execute", execute)
    monkeypatch.setattr(MediaEngine, "generate_adventure_cover", generate)
    response = await auth_client.post(
        "/api/adventures/portrait-template/visuals/regenerate",
        json={"target_type": "cover", "target_id": "cover"},
    )
    assert response.status_code == 200, response.text
    assert len(generated) == 1
    assert len(writes) == 2 and writes[0] is not writes[1]


async def test_dynamic_scene_save_retries_without_regenerating(portrait_world, monkeypatch):
    scene_id, _ = await seed()
    monkeypatch.setattr(persistence, "RETRY_DELAYS", (0,))
    original = images._load
    loads = []

    async def load(db, *args):
        loads.append(db)
        result = await original(db, *args)
        if len(loads) == 2:
            raise sqlite3.OperationalError("database is locked")
        return result

    monkeypatch.setattr(images, "_load", load)
    async with TestSessionLocal() as db:
        owner = (await db.scalars(select(User))).first().id
    await images._generate("portrait-session", scene_id, owner)
    assert len(portrait_world) == 1
    assert len(loads) == 3 and loads[1] is not loads[2]
    async with TestSessionLocal() as db:
        scene = await db.scalar(select(WorldScene).where(WorldScene.id == scene_id))
        assert scene.image_url


@pytest.mark.parametrize("change", ["edit", "image", "delete"])
async def test_dynamic_scene_source_change_keeps_newer_state(portrait_world, monkeypatch, change):
    scene_id, _ = await seed()
    async with TestSessionLocal() as db:
        owner = (await db.scalars(select(User))).first().id
    original = MediaEngine.generate_image

    async def generate(**kwargs):
        async with TestSessionLocal() as db:
            scene = await db.scalar(select(WorldScene).where(WorldScene.id == scene_id))
            if change == "delete":
                await db.delete(scene)
            elif change == "image":
                scene.image_url = "/data/newer.png"
            else:
                scene.description = "Changed description"
            await db.commit()
        return await original(**kwargs)

    monkeypatch.setattr(MediaEngine, "generate_image", generate)
    await images._run("portrait-session", scene_id, owner)
    assert images._results[("portrait-session", scene_id)] == (
        "ready" if change == "image" else "missing"
    )
    async with TestSessionLocal() as db:
        scene = await db.scalar(select(WorldScene).where(WorldScene.id == scene_id))
        if change == "delete":
            assert scene is None
        elif change == "image":
            assert scene.image_url == "/data/newer.png"
        else:
            assert scene.image_url is None
