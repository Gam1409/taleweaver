"""Image settings shown in the editor must match the workflow actually submitted."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.core.comfyui_config import select_workflow
from backend.engine.media_engine import MediaEngine
from backend.models.adventure_template import AdventureTemplate
from backend.models.user import User
from backend.models.world_entity import WorldScene
from tests.conftest import TestSessionLocal
from tests.test_comfyui import workflow

__all__ = ["workflow"]
PATH = "/api/adventures/image-settings-story/visual-presets"


@pytest.fixture
async def image_story(setup_test_db, auth_client, workflow):
    old = deepcopy(workflow)
    old["name"] = "Saved Anima background"
    old["graph"]["model"] = {
        "class_type": "UNETLoader",
        "inputs": {"unet_name": "old-anima.safetensors"},
    }
    current = deepcopy(old)
    current["name"] = "Current Nova background"
    current["graph"]["model"]["inputs"]["unet_name"] = "installed-nova.safetensors"
    async with TestSessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == "test_user"))
        user.t2i_settings = {
            "comfyui_presets": {
                "old": {"name": "Saved Anima", "generate": old},
                "current": {"name": "Nova Anima", "generate": current},
            },
            "comfyui_assignments": {"advanced": "current", "background": "current"},
            "comfyui_test_preset": "current",
            "advanced_model_provider": "comfyui",
        }
        db.add(
            AdventureTemplate(
                id="image-settings-story",
                owner_id=user.id,
                title="Clinic",
                original_manifest={
                    "visual_preset_source": "saved",
                    "visual_presets": {"background": "old"},
                    "plot": "Keep this story",
                },
            )
        )
        db.add(
            WorldScene(
                id="IMAGE_SETTINGS_LAB",
                template_id="image-settings-story",
                label="Laboratory",
                description="An empty laboratory.",
                image_url="/data/old.png",
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_current_source_changes_next_generation_and_survives_reload(
    auth_client, image_story, monkeypatch
):
    before = await auth_client.get(PATH, params={"purpose": "background", "advanced": True})
    assert before.status_code == 200
    assert before.json()["effective"]["preset_name"] == "Saved Anima"
    assert before.json()["effective"]["models"][0]["file"] == "old-anima.safetensors"
    saved = await auth_client.put(PATH, json={"source": "current"})
    assert saved.status_code == 200, saved.text
    reloaded = (
        await auth_client.get(PATH, params={"purpose": "background", "advanced": True})
    ).json()
    assert reloaded["source"] == "current"
    assert reloaded["selection"] == {"background": "old"}
    assert reloaded["effective"]["preset_name"] == "Nova Anima"
    assert reloaded["effective"]["models"][0]["file"] == "installed-nova.safetensors"
    generated = AsyncMock(return_value="/data/new.png")
    monkeypatch.setattr(MediaEngine, "generate_scene_image", generated)
    response = await auth_client.post(
        "/api/adventures/image-settings-story/visuals/regenerate",
        json={
            "target_type": "scene",
            "target_id": "IMAGE_SETTINGS_LAB",
            "prompt": "An empty laboratory.",
            "use_advanced_model": True,
        },
    )
    assert response.status_code == 200, response.text
    config = generated.call_args.kwargs["user_config"]["t2i_settings"]
    actual = select_workflow(
        {**config, "comfyui_profile": "advanced", "image_purpose": "background"}
    )
    assert actual.name == reloaded["effective"]["workflow_name"]
    assert actual.graph["model"]["inputs"]["unet_name"] == "installed-nova.safetensors"
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, "image-settings-story")
        assert adventure.original_manifest["plot"] == "Keep this story"
        scene = await db.scalar(select(WorldScene).where(WorldScene.id == "IMAGE_SETTINGS_LAB"))
        assert scene.image_url == "/data/new.png"
    restored = await auth_client.put(
        PATH, json={"source": "saved", "selection": {"background": "old"}}
    )
    assert restored.status_code == 200
    assert (await auth_client.get(PATH, params={"purpose": "background"})).json()["effective"][
        "preset_name"
    ] == "Saved Anima"


@pytest.mark.asyncio
async def test_missing_saved_preset_can_be_bypassed_without_losing_selection(
    auth_client, image_story
):
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, "image-settings-story")
        adventure.original_manifest = {
            **adventure.original_manifest,
            "visual_presets": {"background": "removed"},
        }
        await db.commit()
    response = await auth_client.get(PATH, params={"purpose": "background"})
    assert response.status_code == 200
    assert "unavailable" in response.json()["effective"]["error"]
    response = await auth_client.put(
        PATH, json={"source": "current", "selection": {"background": "removed"}}
    )
    assert response.status_code == 200
    response = await auth_client.get(PATH, params={"purpose": "background"})
    assert response.json()["effective"]["preset_name"] == "Nova Anima"
    assert response.json()["selection"] == {"background": "removed"}


@pytest.mark.asyncio
async def test_reference_variant_unavailable_still_allows_source_edit(auth_client, image_story):
    response = await auth_client.get(PATH, params={"purpose": "background", "reference": True})
    assert response.status_code == 200
    assert "incomplete" in response.json()["effective"]["error"]
    assert response.json()["source"] == "saved"


@pytest.mark.asyncio
async def test_other_owners_cannot_read_or_change_image_settings(auth_client, image_story):
    async with TestSessionLocal() as db:
        other = User(username="image-settings-other", hashed_password="unused")
        db.add(other)
        await db.flush()
        adventure = await db.get(AdventureTemplate, "image-settings-story")
        adventure.owner_id = other.id
        await db.commit()
    assert (await auth_client.get(PATH, params={"purpose": "background"})).status_code == 404
    assert (
        await auth_client.put(PATH, json={"source": "current", "selection": {}})
    ).status_code == 404


@pytest.mark.asyncio
async def test_source_only_change_preserves_newer_saved_assignments(auth_client, image_story):
    await auth_client.get(PATH)
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, "image-settings-story")
        adventure.original_manifest = {
            **adventure.original_manifest,
            "visual_presets": {"background": "current"},
        }
        await db.commit()
    response = await auth_client.put(PATH, json={"source": "current"})
    assert response.status_code == 200
    assert response.json()["selection"] == {"background": "current"}
    reloaded = (await auth_client.get(PATH)).json()
    assert reloaded["selection"] == {"background": "current"}
