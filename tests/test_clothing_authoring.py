"""Editor wearable metadata must feed runtime clothing without changing ownership."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import select

from backend.api.routes.adventures.editing import item_generation
from backend.engine.clothing.actions import WardrobeAction
from backend.engine.clothing.projection import visible_character
from backend.engine.clothing.runtime import _change_wear
from backend.engine.clothing.schema import Garment, VisualProfile
from backend.engine.clothing.visuals import canonical_inventory, character_visuals
from backend.models.adventure_template import AdventureTemplate
from backend.models.user import User
from backend.models.world_entity import WorldEntity, WorldScene
from tests.conftest import TestSessionLocal

COAT = {"category": "clothing", "layer": 3, "coverage": ["torso", "arms"], "opaque": True}


def test_accessory_does_not_hide_clothing_but_can_be_hidden_itself():
    items = [
        {"id": "shirt", "name": "Shirt", "clothing": {**COAT, "layer": 2}},
        {"id": "coat", "name": "Coat", "clothing": COAT},
        {
            "id": "locket",
            "name": "Locket",
            "clothing": {
                "category": "accessory",
                "coverage": ["torso"],
                "layer": 4,
                "opaque": True,
            },
        },
    ]
    profile = VisualProfile(worn=[{"item_id": item["id"]} for item in items])
    projected = visible_character(profile, items)
    assert [item["item_id"] for item in projected["clothing"]] == ["coat", "locket"]
    items[-1]["clothing"]["layer"] = 1
    assert [item["item_id"] for item in visible_character(profile, items)["clothing"]] == ["coat"]
    # Legacy metadata keeps the previous opaque clothing behavior.
    assert Garment.model_validate({"layer": 2, "coverage": ["torso"]}).category == "clothing"


async def seed():
    async with TestSessionLocal() as db:
        user = (await db.execute(select(User).where(User.username == "test_user"))).scalar_one()
        adventure = AdventureTemplate(title="Wardrobe", owner_id=user.id)
        db.add(adventure)
        await db.flush()
        db.add(WorldScene(template_id=adventure.id, id="ROOM", label="Room", description="Room"))
        await db.commit()
        return adventure.id


def fake_model(monkeypatch, result):
    call = AsyncMock(return_value=result)
    monkeypatch.setattr(
        item_generation.GameMasterLLM,
        "for_role",
        lambda *_: SimpleNamespace(model="test", aexecute_complex_task=call),
    )
    return call


async def test_editor_create_then_runtime_wear_uses_saved_metadata(auth_client, setup_test_db):
    template_id = await seed()
    response = await auth_client.post(
        f"/api/adventures/{template_id}/editor/entity",
        json={
            "entity_id": "COAT",
            "entity_type": "OBJECT",
            "scene_id": "ROOM",
            "name": "Blue coat",
            "description": "A wool overcoat.",
            "item_type": "WEARABLE",
            "wearable_slots": ["Chest"],
            "clothing": COAT,
        },
    )
    assert response.status_code == 200, response.text
    async with TestSessionLocal() as db:
        item = await db.scalar(select(WorldEntity).where(WorldEntity.template_id == template_id))
        assert item.metadata_json["clothing"]["coverage"] == COAT["coverage"]
        owned = canonical_inventory([{"id": "COAT"}], [item])
        profile = VisualProfile(appearance={"hair": "black"}).model_dump()
        actor = {
            "visual_profile": profile,
            "inventory": [{"id": "COAT"}],
            "resolved_inventory": owned,
            "equipment": {},
        }
        assert character_visuals(actor, owned)["clothing_detail_limited"] is True
        _change_wear(
            actor,
            WardrobeAction(
                actor_id="PLAYER",
                source="player_action",
                evidence="I put on my coat.",
                basis="performed",
                agency="self_action",
                reason="The player dresses.",
                operation="wear",
                item_id="COAT",
            ),
        )
        assert actor["visual_profile"]["worn"] == [{"item_id": "COAT", "uncovered_regions": []}]
        assert "Blue coat" in character_visuals(actor, owned)["clothing"]
        assert actor["inventory"] == [{"id": "COAT"}]


async def test_preparation_keeps_existing_values_and_does_not_save(
    auth_client, setup_test_db, monkeypatch
):
    template_id = await seed()
    call = fake_model(monkeypatch, Garment(**COAT))
    existing = {"layer": 1, "opaque": False, "description": "Author's color", "underwear": False}
    response = await auth_client.post(
        f"/api/adventures/{template_id}/editor/prepare-clothing",
        json={
            "name": "A sheer shawl",
            "description": "A blue shawl",
            "wearable_slots": ["Chest"],
            "clothing": existing,
        },
    )
    assert response.status_code == 200, response.text
    assert all(response.json()[key] == value for key, value in existing.items())
    assert response.json()["coverage"] == ["torso", "arms"]
    assert call.call_count == 1
    async with TestSessionLocal() as db:
        assert (
            await db.scalars(select(WorldEntity).where(WorldEntity.template_id == template_id))
        ).all() == []


async def test_existing_complete_properties_do_not_need_llm(
    auth_client, setup_test_db, monkeypatch
):
    template_id = await seed()
    call = fake_model(monkeypatch, {})
    response = await auth_client.post(
        f"/api/adventures/{template_id}/editor/prepare-clothing",
        json={
            "name": "Coat",
            "clothing": COAT,
        },
    )
    assert response.status_code == 200
    call.assert_not_called()


async def test_editor_update_preserves_other_metadata_and_validates(auth_client, setup_test_db):
    template_id = await seed()
    async with TestSessionLocal() as db:
        db.add(
            WorldEntity(
                id="COAT",
                template_id=template_id,
                entity_type="OBJECT",
                name="Coat",
                description="Coat",
                current_scene_id="ROOM",
                item_type="WEARABLE",
                metadata_json={"on_pickup_text": "A gift"},
            )
        )
        await db.commit()
    url = f"/api/adventures/{template_id}/editor/entity"
    payload = {"target_id": "COAT", "target_type": "object", "clothing": COAT}
    assert (await auth_client.patch(url, json=payload)).status_code == 200
    async with TestSessionLocal() as db:
        item = await db.scalar(select(WorldEntity).where(WorldEntity.template_id == template_id))
        assert item.metadata_json["on_pickup_text"] == "A gift"
        assert item.metadata_json["clothing"]["category"] == "clothing"
    response = await auth_client.patch(url, json={**payload, "clothing": {**COAT, "coverage": []}})
    assert response.status_code == 422


async def test_invalid_preparation_and_missing_adventure_never_call_model(
    auth_client, setup_test_db, monkeypatch
):
    call = fake_model(monkeypatch, {})
    url = "/api/adventures/missing/editor/prepare-clothing"
    assert (
        await auth_client.post(url, json={"name": "Coat", "clothing": {"layer": 9}})
    ).status_code == 422
    assert (await auth_client.post(url, json={"name": "Coat"})).status_code == 404
    call.assert_not_called()


async def test_wearable_generation_requires_garment_data(auth_client, setup_test_db, monkeypatch):
    template_id = await seed()
    fake_model(
        monkeypatch,
        {"name": "Coat", "description": "Blue coat", "item_type": "WEARABLE", "is_portable": True},
    )
    response = await auth_client.post(
        f"/api/adventures/{template_id}/editor/generate-item-draft",
        json={"brief": "A blue coat", "item_type": "WEARABLE"},
    )
    assert response.status_code == 502
