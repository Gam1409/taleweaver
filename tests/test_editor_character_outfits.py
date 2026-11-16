"""Existing wardrobes are context, not a request to replace a character or duplicate clothes."""

import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from backend.core.llm_router import GameMasterLLM
from backend.models.adventure_template import AdventureTemplate
from backend.models.avatar import Avatar
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_editor_entity_update import _seed

pytestmark = pytest.mark.asyncio
COAT = {
    "item_id": "COAT",
    "name": "White coat",
    "description": "A crisp white medical coat.",
    "wearable_slots": ["Chest"],
    "clothing": {"layer": 3, "coverage": ["torso", "arms"]},
}
SKIRT = {
    "name": "Grey skirt",
    "description": "A charcoal wool skirt with precise seams and a narrow back vent.",
    "wearable_slots": ["Legs"],
    "clothing": {"layer": 2, "coverage": ["pelvis", "legs"]},
}
BRA = {
    "item_id": "BRA",
    "name": "Red bra",
    "description": "A red silk bra with adjustable straps.",
    "wearable_slots": ["Chest"],
    "clothing": {"layer": 0, "coverage": ["torso"], "underwear": True},
}


async def seed(kind):
    template = await _seed()
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, template)
        adventure.original_manifest = {
            "plot": "Keep the plot",
            "clothing_settings": {"detailed": True},
            "nsfw_settings": {"enabled": True},
        }
        model = Avatar if kind == "protagonist" else WorldEntity
        actor = await db.scalar(select(model).where(model.template_id == template))
        actor.age_years = 32
        actor.description = "A reserved doctor with dark hair and grey eyes."
        actor.goal = "Identify contamination."
        actor.inventory = ["COAT", "BRA", "KEY"]
        actor.visual_profile = {
            "version": 1,
            "appearance": {"age_years": 32, "hair": "dark", "eyes": "grey"},
            "worn": [{"item_id": "COAT"}],
        }
        for spec in (COAT, BRA):
            db.add(
                WorldEntity(
                    id=spec["item_id"],
                    template_id=template,
                    entity_type="OBJECT",
                    name=spec["name"],
                    description=spec["description"],
                    item_type="WEARABLE",
                    current_scene_id="INVENTORY",
                    is_in_inventory=True,
                    wearable_slots=spec["wearable_slots"],
                    metadata_json={"clothing": spec["clothing"]},
                )
            )
        db.add(
            WorldEntity(
                id="KEY",
                template_id=template,
                entity_type="OBJECT",
                name="Laboratory key",
                description="A brass key.",
                current_scene_id="INVENTORY",
                is_in_inventory=True,
                item_type="DEFAULT",
            )
        )
        await db.commit()
        return template, actor.id


def fake(monkeypatch, draft):
    call = AsyncMock(return_value=draft)
    monkeypatch.setattr(
        GameMasterLLM,
        "for_role",
        lambda *_: SimpleNamespace(model="mock", aexecute_complex_task=call),
    )
    return call


@pytest.mark.parametrize("kind", ["npc", "protagonist"])
async def test_preview_reads_worn_and_owned_reuses_existing_and_never_writes(
    auth_client, monkeypatch, kind
):
    template, actor_id = await seed(kind)
    call = fake(monkeypatch, {"outfit": [COAT, BRA, SKIRT]})
    response = await auth_client.post(
        f"/api/adventures/{template}/editor/generate-character-outfit",
        json={"target_type": kind, "target_id": actor_id, "include_underwear": True},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert [item["name"] for item in data["draft"]["outfit"]] == [BRA["name"], SKIRT["name"]]
    assert data["draft"]["outfit"][0]["item_id"] == "BRA"
    assert data["notes"] == ["Already worn: White coat."]
    context = json.loads(call.call_args.kwargs["user_prompt"])
    assert {item["id"]: item["worn"] for item in context["owned"]} == {"COAT": True, "BRA": False}
    async with TestSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(WorldEntity)) == 4


@pytest.mark.parametrize("kind", ["npc", "protagonist"])
async def test_save_card_adds_selected_clothes_atomically_without_losing_old_items(
    auth_client, kind
):
    template, actor_id = await seed(kind)
    payload = {
        "target_type": kind,
        "target_id": actor_id,
        "name": "Edited doctor",
        "outfit_completion": {"outfit": [COAT, BRA, SKIRT]},
    }
    response = await auth_client.patch(f"/api/adventures/{template}/editor/entity", json=payload)
    assert response.status_code == 200, response.text
    async with TestSessionLocal() as db:
        model = Avatar if kind == "protagonist" else WorldEntity
        actor = await db.scalar(
            select(model).where(model.template_id == template, model.id == actor_id)
        )
        assert actor.name == "Edited doctor"
        ids = {item["id"] if isinstance(item, dict) else item for item in actor.inventory}
        assert {"COAT", "BRA", "KEY"} < ids
        worn = {item["item_id"] for item in actor.visual_profile["worn"]}
        assert {"COAT", "BRA"} < worn
        assert actor.visual_profile["appearance"]["hair"] == "dark"
        assert actor.goal == "Identify contamination."
        assert await db.scalar(select(func.count()).select_from(WorldEntity)) == 5
        skirt = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.template_id == template, WorldEntity.name == SKIRT["name"]
            )
        )
        assert skirt.id == skirt.id.upper()
        assert skirt.id in ids and skirt.id in worn
    repeat = await auth_client.patch(f"/api/adventures/{template}/editor/entity", json=payload)
    assert repeat.status_code == 200
    async with TestSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(WorldEntity)) == 5


async def test_policy_failure_rolls_back_card_edits_and_all_new_clothes(auth_client):
    template, actor_id = await seed("npc")
    async with TestSessionLocal() as db:
        actor = await db.scalar(select(WorldEntity).where(WorldEntity.id == actor_id))
        actor.age_years = 17
        previous_name = actor.name
        await db.commit()
    response = await auth_client.patch(
        f"/api/adventures/{template}/editor/entity",
        json={
            "target_type": "npc",
            "target_id": actor_id,
            "name": "Must not be saved",
            "outfit_completion": {
                "outfit": [SKIRT, {**BRA, "clothing": {**BRA["clothing"], "underwear": False}}]
            },
        },
    )
    assert response.status_code == 400, response.text
    async with TestSessionLocal() as db:
        actor = await db.scalar(select(WorldEntity).where(WorldEntity.id == actor_id))
        assert actor.name == previous_name
        assert await db.scalar(select(func.count()).select_from(WorldEntity)) == 4


async def test_foreign_items_are_rejected_and_missing_targets_never_call_model(
    auth_client, monkeypatch
):
    template, actor_id = await seed("npc")
    call = fake(monkeypatch, {"outfit": [{**SKIRT, "item_id": "NOT_OWNED"}]})
    response = await auth_client.post(
        f"/api/adventures/{template}/editor/generate-character-outfit",
        json={"target_type": "npc", "target_id": actor_id},
    )
    assert response.status_code == 400
    call.reset_mock()
    for path, identifier in ((template, "MISSING"), ("other-adventure", actor_id)):
        result = await auth_client.post(
            f"/api/adventures/{path}/editor/generate-character-outfit",
            json={"target_type": "npc", "target_id": identifier},
        )
        assert result.status_code == 404
    call.assert_not_called()


async def test_invalid_model_result_does_not_change_wardrobe(auth_client, monkeypatch):
    template, actor_id = await seed("npc")
    invalid = deepcopy(SKIRT)
    invalid["clothing"]["coverage"] = ["unknown"]
    fake(monkeypatch, {"outfit": [invalid]})
    response = await auth_client.post(
        f"/api/adventures/{template}/editor/generate-character-outfit",
        json={"target_type": "npc", "target_id": actor_id},
    )
    assert response.status_code == 502


async def test_pending_inventory_is_context_and_uses_the_same_object_on_save(
    auth_client, monkeypatch
):
    template, actor_id = await seed("npc")
    scarf = {
        "item_id": "SCARF",
        "name": "Silk scarf",
        "description": "A blue silk scarf.",
        "wearable_slots": ["Neck"],
        "clothing": {"category": "accessory", "layer": 4, "coverage": ["torso"]},
    }
    async with TestSessionLocal() as db:
        db.add(
            WorldEntity(
                id="SCARF",
                template_id=template,
                entity_type="OBJECT",
                name=scarf["name"],
                description=scarf["description"],
                item_type="WEARABLE",
                current_scene_id="HALL",
                wearable_slots=["Neck"],
                metadata_json={"clothing": scarf["clothing"]},
            )
        )
        await db.commit()
    call = fake(monkeypatch, {"outfit": [scarf]})
    preview = await auth_client.post(
        f"/api/adventures/{template}/editor/generate-character-outfit",
        json={
            "target_type": "npc",
            "target_id": actor_id,
            "inventory_ids": ["COAT", "BRA", "KEY", "SCARF"],
        },
    )
    assert preview.status_code == 200, preview.text
    context = json.loads(call.call_args.kwargs["user_prompt"])
    pending = next(item for item in context["owned"] if item["id"] == "SCARF")
    assert pending["pending"] and not pending["worn"]
    saved = await auth_client.patch(
        f"/api/adventures/{template}/editor/entity",
        json={
            "target_type": "npc",
            "target_id": actor_id,
            "inventory": ["COAT", "BRA", "KEY", "SCARF"],
            "outfit_completion": preview.json()["draft"],
        },
    )
    assert saved.status_code == 200, saved.text
    async with TestSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(WorldEntity)) == 5
        actor = await db.scalar(select(WorldEntity).where(WorldEntity.id == actor_id))
        assert "SCARF" in {item["item_id"] for item in actor.visual_profile["worn"]}


async def test_legacy_protagonist_equipment_is_preserved_when_initializing_layers(auth_client):
    template, actor_id = await seed("protagonist")
    async with TestSessionLocal() as db:
        actor = await db.get(Avatar, actor_id)
        actor.visual_profile = None
        actor.equipment = {"Chest": {"id": "COAT", "name": "White coat"}}
        await db.commit()
    response = await auth_client.patch(
        f"/api/adventures/{template}/editor/entity",
        json={
            "target_type": "protagonist",
            "target_id": "protagonist",
            "outfit_completion": {"appearance": {"hair": "dark"}, "outfit": [SKIRT]},
        },
    )
    assert response.status_code == 200, response.text
    async with TestSessionLocal() as db:
        actor = await db.get(Avatar, actor_id)
        assert actor.equipment["Chest"]["id"] == "COAT"
        assert "COAT" in {item["item_id"] for item in actor.visual_profile["worn"]}
        assert len(actor.visual_profile["worn"]) == 2


async def test_identical_owned_names_require_an_explicit_id(auth_client, monkeypatch):
    template, actor_id = await seed("npc")
    async with TestSessionLocal() as db:
        actor = await db.scalar(select(WorldEntity).where(WorldEntity.id == actor_id))
        actor.inventory = [*actor.inventory, "SPARE_BRA"]
        db.add(
            WorldEntity(
                id="SPARE_BRA",
                template_id=template,
                entity_type="OBJECT",
                name=BRA["name"],
                description="A second red bra.",
                item_type="WEARABLE",
                current_scene_id="INVENTORY",
                wearable_slots=["Chest"],
                metadata_json={"clothing": BRA["clothing"]},
            )
        )
        await db.commit()
    proposal = {key: value for key, value in BRA.items() if key != "item_id"}
    call = fake(monkeypatch, {"outfit": [proposal]})
    request = {"target_type": "npc", "target_id": actor_id, "include_underwear": True}
    rejected = await auth_client.post(
        f"/api/adventures/{template}/editor/generate-character-outfit", json=request
    )
    assert rejected.status_code == 400
    assert "same name" in rejected.json()["detail"]
    call.return_value = {"outfit": [BRA]}
    accepted = await auth_client.post(
        f"/api/adventures/{template}/editor/generate-character-outfit", json=request
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["draft"]["outfit"][0]["item_id"] == "BRA"
