"""Settings persistence, image role selection and owner-scoped visual jobs."""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

from backend.api.routes import config_api, visual_jobs
from backend.core.config import settings
from backend.engine.comfyui_client import ComfyClient
from backend.engine.media_engine import MediaEngine
from backend.models.avatar import Avatar
from backend.models.user import User
from tests.conftest import TestSessionLocal
from tests.test_adventures_api import _create_adventure
from tests.test_comfyui import comfy_options, registry, workflow

__all__ = ["comfy_options", "registry", "workflow"]

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def isolate_jobs(monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_PRIVATE_NETWORK_MODELS", True)

    async def empty_models(*args):
        return []

    monkeypatch.setattr(config_api, "_fetch_ollama_models", empty_models)
    yield
    tasks = [j.task for j in visual_jobs._jobs.values() if j.task]
    for task in tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    visual_jobs._jobs.clear()


async def test_save_and_reload_workflows_without_model_name(auth_client, comfy_options):
    for timeout in (300, 600):
        comfy_options["comfyui_timeout"] = timeout
        response = await auth_client.post("/api/settings/t2i", json=comfy_options)
        assert response.status_code == 200, response.text
        loaded = (await auth_client.get("/api/settings")).json()
        assert loaded["is_t2i_configured"]
        assert loaded["t2i_settings"]["comfyui_timeout"] == timeout
        assert (
            loaded["t2i_settings"]["comfyui_profiles"]["simple"]["generate"]["graph"]
            == comfy_options["comfyui_profiles"]["simple"]["generate"]["graph"]
        )
        assert any(p["id"] == "comfyui" for p in loaded["available_constants"]["image_providers"])


async def test_reject_incomplete_comfy_settings(auth_client, comfy_options):
    comfy_options["comfyui_profiles"] = {}
    response = await auth_client.post("/api/settings/t2i", json=comfy_options)
    assert response.status_code == 400


async def test_only_admin_can_execute_workflow_drafts(auth_client):
    async with TestSessionLocal() as db:
        user = (await db.execute(select(User))).scalars().first()
        user.role = "user"
        await db.commit()
    payload = {"provider": "comfyui", "model": ""}
    direct = await auth_client.post("/api/settings/test-vision", json=payload)
    queued = await auth_client.post(
        "/api/settings/visual-jobs",
        json={"id": str(uuid4()), "operation": "test", "payload": payload},
    )
    assert direct.status_code == queued.status_code == 403


async def test_check_reports_missing_nodes_without_generation(
    auth_client, workflow, registry, monkeypatch
):
    calls = []
    del registry["KSampler"]

    async def get_registry(self, method, path, **kwargs):
        calls.append((method, path))
        return registry

    monkeypatch.setattr(ComfyClient, "json", get_registry)
    response = await auth_client.post(
        "/api/settings/comfyui/check", json={"url": "http://127.0.0.1:8188", "workflow": workflow}
    )
    assert response.status_code == 200
    assert response.json()["missing_node_types"] == ["KSampler"]
    assert calls == [("GET", "/object_info")]


async def test_regeneration_honors_override_and_keeps_previous_image_on_failure(
    auth_client, monkeypatch
):
    ids = await _create_adventure(auth_client, "Image profile routing")
    captured = []

    async def generate(**kwargs):
        captured.append(kwargs["use_advanced_model"])
        return "/data/kept.png" if len(captured) < 3 else None

    monkeypatch.setattr(MediaEngine, "generate_entity_image", generate)
    path = f"/api/adventures/{ids['adventure_id']}/visuals/regenerate"
    for override in (True, False):
        response = await auth_client.post(
            path,
            json={
                "target_type": "protagonist",
                "target_id": ids["avatar_id"],
                "use_advanced_model": override,
            },
        )
        assert response.status_code == 200, response.text
    assert captured == [True, False]
    response = await auth_client.post(
        path, json={"target_type": "protagonist", "target_id": ids["avatar_id"]}
    )
    assert response.status_code == 400
    async with TestSessionLocal() as db:
        avatar = await db.get(Avatar, ids["avatar_id"])
        assert avatar.profile_image == "/data/kept.png"


async def test_reference_rejects_another_adventure_file(auth_client, monkeypatch):
    ids = await _create_adventure(auth_client, "Reference access")
    async with TestSessionLocal() as db:
        user = (await db.execute(select(User))).scalars().first()
        user.t2i_settings = {"advanced_model_provider": "comfyui"}
        avatar = await db.get(Avatar, ids["avatar_id"])
        avatar.profile_image = "/data/adventures/library/someone-else/portrait.png"
        await db.commit()
    response = await auth_client.post(
        f"/api/adventures/{ids['adventure_id']}/visuals/regenerate",
        json={
            "target_type": "protagonist",
            "target_id": ids["avatar_id"],
            "use_current_image": True,
        },
    )
    assert response.status_code == 400


async def test_job_is_idempotent_and_owner_scoped(auth_client, monkeypatch):
    gate = asyncio.Event()
    calls = []

    async def generate(request, user, db):
        calls.append(request.id)
        await gate.wait()
        return {"status": "success", "image_url": "/data/test.png"}

    monkeypatch.setattr(visual_jobs, "_dispatch", generate)
    body = {
        "id": str(uuid4()),
        "operation": "test",
        "payload": {"model": "x", "provider": "comfyui"},
    }
    response = await auth_client.post("/api/settings/visual-jobs", json=body)
    assert response.status_code == 200
    assert (await auth_client.post("/api/settings/visual-jobs", json=body)).status_code == 200
    other_request = {**body, "id": str(uuid4())}
    assert (
        await auth_client.post("/api/settings/visual-jobs", json=other_request)
    ).status_code == 409
    job = visual_jobs._jobs[body["id"]]
    with pytest.raises(HTTPException) as denied:
        visual_jobs._owned_job(job.request.id, SimpleNamespace(id="other-user"))
    assert denied.value.status_code == 404
    gate.set()
    await job.task
    result = await auth_client.get(f"/api/settings/visual-jobs/{body['id']}")
    assert result.json()["state"] == "succeeded"
    assert len(calls) == 1


async def test_job_cancellation_is_honest(auth_client, monkeypatch):
    entered = asyncio.Event()

    async def blocked(*args):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(visual_jobs, "_dispatch", blocked)
    body = {
        "id": str(uuid4()),
        "operation": "test",
        "payload": {"model": "x", "provider": "comfyui"},
    }
    await auth_client.post("/api/settings/visual-jobs", json=body)
    await entered.wait()
    await auth_client.delete(f"/api/settings/visual-jobs/{body['id']}")
    await visual_jobs._jobs[body["id"]].task
    result = (await auth_client.get(f"/api/settings/visual-jobs/{body['id']}")).json()
    assert result["state"] == "abandoned"
    assert "may continue" in result["message"]


@pytest.mark.parametrize("operation", ["test", "catalog", "avatar", "asset"])
async def test_job_dispatch_for_each_image_entry_point(auth_client, monkeypatch, operation):
    ids = await _create_adventure(auth_client, "Visual jobs")
    async with TestSessionLocal() as db:
        user = (await db.execute(select(User))).scalars().first()
        user.t2i_settings = {
            "simple_model": "image",
            "simple_model_provider": "ollama",
            "advanced_model": "image",
            "advanced_model_provider": "ollama",
        }
        await db.commit()

    async def generate(**kwargs):
        return "/data/test-image.png"

    monkeypatch.setattr(MediaEngine, "generate_image", generate)
    payloads = {
        "test": {"model": "image", "provider": "ollama"},
        "catalog": {"catalog_type": "styles", "target_id": "test-style", "name": "Test"},
        "avatar": {"bio": "A sailor"},
        "asset": {"target_type": "protagonist", "target_id": ids["avatar_id"]},
    }
    body = {
        "id": str(uuid4()),
        "operation": operation,
        "payload": payloads[operation],
        "template_id": ids["adventure_id"],
    }
    response = await auth_client.post("/api/settings/visual-jobs", json=body)
    assert response.status_code == 200, response.text
    await visual_jobs._jobs[body["id"]].task
    result = (await auth_client.get(f"/api/settings/visual-jobs/{body['id']}")).json()
    assert result["state"] == "succeeded", result
    assert result["result"].get("image_url") or result["result"].get("profile_image_url")
