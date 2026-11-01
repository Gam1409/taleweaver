"""Item drafting must be owner-scoped, reviewable and independent of scene generation."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from backend.api.routes.adventures.editing import item_generation as module
from backend.models.adventure_template import AdventureTemplate
from backend.models.user import User
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.asyncio


async def seed():
    async with TestSessionLocal() as db:
        user = (await db.execute(select(User).where(User.username == "test_user"))).scalar_one()
        adventure = AdventureTemplate(
            title="Hospital", owner_id=user.id, original_prompt="Modern Japan"
        )
        db.add(adventure)
        await db.commit()
        return adventure.id


def fake_model(monkeypatch, result):
    call = AsyncMock(return_value=result)
    monkeypatch.setattr(
        module.GameMasterLLM,
        "for_role",
        lambda *_: SimpleNamespace(model="test", aexecute_complex_task=call),
    )
    return call


async def test_draft_does_not_create_item_and_preserves_slot(
    auth_client, setup_test_db, monkeypatch
):
    template_id = await seed()
    call = fake_model(
        monkeypatch,
        {
            "name": "Медальон",
            "description": "Серебряный медальон с фотографией Мики.",
            "item_type": "WEARABLE",
            "is_portable": True,
            "wearable_slots": ["Finger"],
        },
    )
    response = await auth_client.post(
        f"/api/adventures/{template_id}/editor/generate-item-draft",
        json={
            "brief": "Медальон с фотографией Мики. Без магии.",
            "item_type": "WEARABLE",
            "wearable_slots": ["Neck"],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["wearable_slots"] == ["Neck"]
    assert "Без магии" in call.call_args.kwargs["user_prompt"]
    async with TestSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(WorldEntity)) == 0


async def test_missing_adventure_does_not_call_model(auth_client, setup_test_db, monkeypatch):
    call = fake_model(monkeypatch, {})
    response = await auth_client.post(
        "/api/adventures/missing/editor/generate-item-draft",
        json={
            "brief": "A key",
            "item_type": "DEFAULT",
        },
    )
    assert response.status_code == 404
    call.assert_not_called()


@pytest.mark.parametrize("brief", [" ", "x" * 2001])
async def test_invalid_brief_rejected(auth_client, setup_test_db, monkeypatch, brief):
    call = fake_model(monkeypatch, {})
    response = await auth_client.post(
        "/api/adventures/missing/editor/generate-item-draft",
        json={
            "brief": brief,
            "item_type": "DEFAULT",
        },
    )
    assert response.status_code == 422
    call.assert_not_called()


async def test_description_uses_existing_item_details(auth_client, setup_test_db, monkeypatch):
    template_id = await seed()
    call = fake_model(monkeypatch, {"description": "A worn brass key."})
    response = await auth_client.post(
        f"/api/adventures/{template_id}/editor/generate-item-description",
        json={
            "name": "Ward key",
            "description": "Brass, with a blue tag",
            "item_type": "DEFAULT",
        },
    )
    assert response.status_code == 200
    context = json.loads(call.call_args.kwargs["user_prompt"])
    assert context["description"] == "Brass, with a blue tag"
    assert context["item_type"] == "DEFAULT"
    assert "Describe the ITEM" in call.call_args.kwargs["system_prompt"]


async def test_invalid_model_result_is_not_returned(auth_client, setup_test_db, monkeypatch):
    template_id = await seed()
    fake_model(monkeypatch, {"name": "Bad draft", "script": "invented"})
    response = await auth_client.post(
        f"/api/adventures/{template_id}/editor/generate-item-draft",
        json={
            "brief": "A key",
            "item_type": "DEFAULT",
        },
    )
    assert response.status_code == 502


async def test_readable_description_limit(auth_client, setup_test_db, monkeypatch):
    template_id = await seed()
    fake_model(monkeypatch, {"description": "x" * 201})
    response = await auth_client.post(
        f"/api/adventures/{template_id}/editor/generate-item-description",
        json={
            "name": "Letter",
            "item_type": "READABLE",
        },
    )
    assert response.status_code == 502
