"""Session NPC portrait jobs use isolated DB/assets and never call a model server."""

import asyncio
import io
import json
import zipfile
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from PIL import Image
from sqlalchemy import select

from backend.api.routes import visual_jobs
from backend.api.routes.adventures.logic import AdventureLogic
from backend.core.config import settings
from backend.engine.media_engine import MediaEngine
from backend.engine.session_exporter import SessionExporter
from backend.models.adventure_template import AdventureTemplate
from backend.models.avatar import Avatar
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.models.world_entity import WorldEntity
from backend.utils.path_security import local_path_to_data_url
from tests.conftest import TestSessionLocal
from tests.test_comfyui import workflow

__all__ = ["workflow"]

OLD_IMAGE = "/data/old-portrait.png"


@pytest_asyncio.fixture
async def portrait_world(auth_client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    visual_jobs._jobs.clear()
    Image.new("RGB", (16, 24)).save(tmp_path / "old-portrait.png")
    async with TestSessionLocal() as db:
        user = (await db.execute(select(User))).scalars().first()
        user.t2i_settings = {
            "simple_model_provider": "stable_diffusion",
            "simple_model": "simple-checkpoint",
            "advanced_model_provider": "stable_diffusion",
            "advanced_model": "portrait-checkpoint",
            "profile_model_quality": "advanced",
            "advanced_min_long_edge": 768,
            "advanced_steps": 24,
            "image_format": "png",
        }
        template = AdventureTemplate(id="portrait-template", title="Forest", owner_id=user.id)
        avatar = Avatar(id="portrait-avatar", name="Hero", user_id=user.id)
        db.add_all([template, avatar])
        await db.flush()
        for sid, owner in [("portrait-session", user.id), ("other-session", "another-owner")]:
            db.add(GameSession(id=sid, user_id=owner, template_id=template.id, avatar_id=avatar.id))
            db.add(
                SessionState(
                    session_id=sid,
                    template_id=template.id,
                    avatar_id=avatar.id,
                    current_scene_id="TOWER",
                    in_game_time=480,
                    entity_states={
                        "NPC_NEW": {
                            "description": "Scarred sailor in a blue coat",
                            "hp": 17,
                            "image_url": OLD_IMAGE,
                        }
                    },
                    quests=[{"id": "quest", "status": "active"}],
                )
            )
            db.add(
                WorldEntity(
                    id="NPC_NEW",
                    session_id=sid,
                    template_id=None,
                    entity_type="NPC",
                    name="Lina",
                    description="Original description",
                    current_scene_id="TOWER",
                    image_url=OLD_IMAGE,
                    hp=30,
                )
            )
        db.add(
            WorldEntity(
                id="NPC_NEW",
                template_id=template.id,
                entity_type="NPC",
                name="Template Lina",
                description="Template only",
                current_scene_id="TOWER",
                image_url=OLD_IMAGE,
            )
        )
        db.add(
            WorldEntity(
                id="ITEM_1",
                session_id="portrait-session",
                entity_type="OBJECT",
                name="Sword",
                description="An item",
                current_scene_id="TOWER",
            )
        )
        await db.commit()
    calls = []

    async def generate(**kwargs):
        calls.append(kwargs)
        path = Path(kwargs["target_dir"]) / kwargs["filename"]
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (32, 48), "blue").save(path)
        return local_path_to_data_url(str(path))

    monkeypatch.setattr(MediaEngine, "generate_image", generate)
    yield calls
    for job in list(visual_jobs._jobs.values()):
        if job.task and not job.task.done():
            job.task.cancel()
            await job.task
    visual_jobs._jobs.clear()


async def start_job(client, session_id="portrait-session", target_id="NPC_NEW", **fields):
    body = {
        "id": str(uuid4()),
        "operation": "session_npc",
        "session_id": session_id,
        "payload": {"target_id": target_id},
        **fields,
    }
    response = await client.post("/api/settings/visual-jobs", json=body)
    assert response.status_code == 200, response.text
    return body


async def finish_job(client, body):
    await visual_jobs._jobs[body["id"]].task
    response = await client.get(f"/api/settings/visual-jobs/{body['id']}")
    assert response.status_code == 200
    return response.json()


async def test_dynamic_npc_persists_on_reload_and_export(auth_client, portrait_world):
    body = await start_job(auth_client)
    result = await finish_job(auth_client, body)
    assert result["state"] == "succeeded", result
    image = result["result"]["image_url"]
    assert image.startswith("/data/adventures/sessions/portrait-session/visuals/entities/")
    request = portrait_world[0]
    assert request["model"] == "portrait-checkpoint"
    assert request["provider_options"]["steps"] == 24
    assert request["provider_options"]["height"] > request["provider_options"]["width"]
    assert "Scarred sailor in a blue coat" in request["prompt"]
    assert "Original description" not in request["prompt"]
    async with TestSessionLocal() as db:
        state = (
            await db.execute(
                select(SessionState).where(SessionState.session_id == "portrait-session")
            )
        ).scalar_one()
        entities = await AdventureLogic.build_session_entities(db, state)
        assert next(e for e in entities if e["id"] == "NPC_NEW")["image_url"] == image
        metadata = await AdventureLogic.get_npc_metadata(db, None, "portrait-session")
        assert metadata["NPC_NEW"]["image_url"] == image
        assert state.in_game_time == 480
        assert state.entity_states["NPC_NEW"]["hp"] == 17
        assert state.quests == [{"id": "quest", "status": "active"}]
        others = (
            (
                await db.execute(
                    select(WorldEntity).where(
                        WorldEntity.id == "NPC_NEW", WorldEntity.session_id != "portrait-session"
                    )
                )
            )
            .scalars()
            .all()
        )
        template = (
            await db.execute(select(WorldEntity).where(WorldEntity.session_id.is_(None)))
        ).scalar_one()
        assert template.image_url == OLD_IMAGE
        assert all(e.image_url == OLD_IMAGE for e in others)
        bundle = await SessionExporter.export_ads(db, "portrait-session")
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        assert f"assets/visuals/entities/{Path(image).name}" in archive.namelist()
        assert Path(image).name in json.dumps(json.loads(archive.read("session.json")))


@pytest.mark.parametrize(
    "session_id,target",
    [
        ("other-session", "NPC_NEW"),
        ("portrait-template", "NPC_NEW"),
        ("missing-session", "NPC_NEW"),
        ("portrait-session", "ITEM_1"),
        ("portrait-session", "missing-npc"),
        ("../portrait-session", "NPC_NEW"),
    ],
)
async def test_only_owned_session_npcs_can_be_changed(
    auth_client, portrait_world, session_id, target
):
    result = await finish_job(auth_client, await start_job(auth_client, session_id, target))
    assert result["state"] == "failed"
    assert "not found" in result["message"]
    assert portrait_world == []


@pytest.mark.parametrize("failure", ["empty", "timeout", "provider"])
async def test_failures_keep_old_portrait_and_state(
    auth_client, portrait_world, monkeypatch, failure
):
    async def generate(**kwargs):
        if failure == "timeout":
            raise TimeoutError
        if failure == "provider":
            raise ValueError("Image workflow needs a missing model")

    monkeypatch.setattr(MediaEngine, "generate_image", generate)
    result = await finish_job(auth_client, await start_job(auth_client))
    assert result["state"] == "failed"
    assert result["message"]
    async with TestSessionLocal() as db:
        npc = (
            await db.execute(
                select(WorldEntity).where(
                    WorldEntity.session_id == "portrait-session", WorldEntity.id == "NPC_NEW"
                )
            )
        ).scalar_one()
        assert npc.image_url == OLD_IMAGE
        state = (
            await db.execute(
                select(SessionState).where(SessionState.session_id == "portrait-session")
            )
        ).scalar_one()
        assert state.entity_states["NPC_NEW"]["image_url"] == OLD_IMAGE
        assert state.in_game_time == 480


async def test_duplicate_jobs_and_cancellation(auth_client, portrait_world, monkeypatch):
    entered = asyncio.Event()

    async def generate(**kwargs):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(MediaEngine, "generate_image", generate)
    body = await start_job(auth_client)
    await asyncio.wait_for(entered.wait(), timeout=3)
    # Irrelevant template_id must not bypass deduplication of a session portrait.
    response = await auth_client.post(
        "/api/settings/visual-jobs", json={**body, "id": str(uuid4()), "template_id": "unrelated"}
    )
    assert response.status_code == 409
    await auth_client.delete(f"/api/settings/visual-jobs/{body['id']}")
    result = await finish_job(auth_client, body)
    assert result["state"] == "abandoned"
    async with TestSessionLocal() as db:
        npc = (
            await db.execute(
                select(WorldEntity).where(
                    WorldEntity.session_id == "portrait-session", WorldEntity.id == "NPC_NEW"
                )
            )
        ).scalar_one()
        assert npc.image_url == OLD_IMAGE


async def test_generation_does_not_rewind_changes_made_while_waiting(
    auth_client, portrait_world, monkeypatch
):
    original = MediaEngine.generate_image

    async def generate(**kwargs):
        async with TestSessionLocal() as db:
            state = (
                await db.execute(
                    select(SessionState).where(SessionState.session_id == "portrait-session")
                )
            ).scalar_one()
            state.in_game_time = 900
            state.current_scene_id = "PORT"
            updated = deepcopy(state.entity_states)
            updated["NPC_NEW"]["hp"] = 9
            updated["NEW_ITEM"] = {"is_in_inventory": True}
            state.entity_states = updated
            await db.commit()
        return await original(**kwargs)

    monkeypatch.setattr(MediaEngine, "generate_image", generate)
    result = await finish_job(auth_client, await start_job(auth_client))
    assert result["state"] == "succeeded", result
    async with TestSessionLocal() as db:
        state = (
            await db.execute(
                select(SessionState).where(SessionState.session_id == "portrait-session")
            )
        ).scalar_one()
        assert state.in_game_time == 900
        assert state.current_scene_id == "PORT"
        assert state.entity_states["NPC_NEW"]["hp"] == 9
        assert state.entity_states["NEW_ITEM"] == {"is_in_inventory": True}


async def test_session_required(auth_client, portrait_world):
    response = await auth_client.post(
        "/api/settings/visual-jobs",
        json={"id": str(uuid4()), "operation": "session_npc", "payload": {"target_id": "NPC_NEW"}},
    )
    assert response.status_code == 422
    assert portrait_world == []


@pytest.mark.parametrize("profile", ["simple", "advanced"])
async def test_saved_story_preset_survives_template_removal(
    auth_client, portrait_world, monkeypatch, workflow, profile
):
    monkeypatch.setattr(settings, "ALLOW_PRIVATE_NETWORK_MODELS", True)
    async with TestSessionLocal() as db:
        user = (await db.execute(select(User))).scalars().first()
        user.t2i_settings = {
            **user.t2i_settings,
            "profile_model_quality": profile,
            "comfyui_url": "http://127.0.0.1:8188",
            "comfyui_presets": {
                "saved-art": {"name": "Saved story", "generate": workflow},
                "current-art": {"name": "Current default", "generate": workflow},
            },
            "comfyui_assignments": {profile: "current-art"},
        }
        state = (
            await db.execute(
                select(SessionState).where(SessionState.session_id == "portrait-session")
            )
        ).scalar_one()
        state.template_id = None
        state.entity_states = {
            **state.entity_states,
            AdventureLogic.SESSION_MANIFEST_SNAPSHOT_KEY: {
                "original_manifest": {"visual_presets": {profile: "saved-art"}}
            },
        }
        await db.commit()
    result = await finish_job(auth_client, await start_job(auth_client))
    assert result["state"] == "succeeded", result
    request = portrait_world[0]
    assert request["provider"] == "comfyui"
    assert request["provider_options"]["comfyui_profile"] == profile
    assert request["provider_options"]["comfyui_assignments"][profile] == "saved-art"
