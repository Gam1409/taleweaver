"""NPC drafts are read-only; publishing creates one canonical owner and its belongings."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from backend.core.llm_router import GameMasterLLM
from backend.engine.adventure_exporter import AdventureExporter
from backend.engine.clothing.visuals import canonical_inventory, character_visuals
from backend.models.adventure_template import AdventureTemplate
from backend.models.user import User
from backend.models.world_entity import WorldEntity, WorldScene
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.asyncio
PATH = "/api/adventures/npc-draft-world/editor"


def item(name, *, layer=None, coverage=None, underwear=False, worn=False):
    return {
        "name": name,
        "description": f"Carefully made {name.lower()} with neatly finished edges.",
        "item_type": "WEARABLE" if layer is not None else "DEFAULT",
        "is_portable": True,
        "wearable_slots": ["Chest"] if layer is not None else [],
        "clothing": {
            "layer": layer,
            "coverage": coverage,
            "underwear": underwear,
        }
        if layer is not None
        else None,
        "worn": worn,
    }


def draft():
    return {
        "name": "Rin",
        "description": "A meticulous doctor with dark hair and grey eyes.",
        "goal": "Identify the source of the contamination.",
        "character": "Reserved and principled; values reliable evidence.",
        "gender": "female",
        "age_years": 32,
        "appearance": {"hair": "dark", "eyes": "grey"},
        "personality_profile": {},
        "items": [
            item("White coat", layer=3, coverage=["torso", "arms"], worn=True),
            item("Red bra", layer=0, coverage=["torso"], underwear=True, worn=True),
            item("Red panties", layer=0, coverage=["pelvis"], underwear=True, worn=True),
            item("Grey skirt", layer=2, coverage=["pelvis", "legs"], worn=True),
            item("Laboratory key"),
        ],
    }


@pytest.fixture
async def npc_world(auth_client, setup_test_db):
    async with TestSessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == "test_user"))
        db.add(
            AdventureTemplate(
                id="npc-draft-world",
                title="Clinic",
                owner_id=user.id,
                original_prompt="Modern hospital",
                original_manifest={
                    "clothing_settings": {"detailed": True},
                    "nsfw_settings": {"enabled": True},
                    "plot": "Keep this plot.",
                },
            )
        )
        db.add(
            WorldScene(
                id="LAB",
                template_id="npc-draft-world",
                label="Laboratory",
                description="An empty laboratory.",
            )
        )
        await db.commit()


def model(monkeypatch, value):
    call = AsyncMock(return_value=value)
    monkeypatch.setattr(
        GameMasterLLM,
        "for_role",
        lambda *_: SimpleNamespace(model="mock", aexecute_complex_task=call),
    )
    return call


async def count_entities():
    async with TestSessionLocal() as db:
        return await db.scalar(select(func.count()).select_from(WorldEntity))


async def test_draft_is_read_only_and_receives_author_options(auth_client, npc_world, monkeypatch):
    call = model(monkeypatch, draft())
    response = await auth_client.post(
        PATH + "/generate-npc-draft",
        json={
            "brief": "A reserved doctor, coat, red underwear and laboratory key.",
            "scene_id": "LAB",
            "age_years": 32,
            "include_clothing": True,
            "include_underwear": True,
            "include_items": True,
        },
    )
    assert response.status_code == 200, response.text
    assert len(response.json()["items"]) == 5
    assert await count_entities() == 0
    assert "Modern hospital" in call.call_args.kwargs["user_prompt"]
    assert '"include_underwear": true' in call.call_args.kwargs["user_prompt"]


async def test_concurrent_retries_publish_once(auth_client, npc_world):
    payload = {"scene_id": "LAB", "creation_id": str(uuid4()), "draft": draft()}
    first, second = await asyncio.gather(
        auth_client.post(PATH + "/npc-with-items", json=payload),
        auth_client.post(PATH + "/npc-with-items", json=payload),
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["npc_id"] == second.json()["npc_id"]
    assert await count_entities() == 6


@pytest.mark.parametrize("disabled", ["clothing", "items", "underwear"])
async def test_model_cannot_ignore_author_options(auth_client, npc_world, monkeypatch, disabled):
    model(monkeypatch, draft())
    response = await auth_client.post(
        PATH + "/generate-npc-draft",
        json={
            "scene_id": "LAB",
            "brief": "A doctor",
            "age_years": 32,
            "include_clothing": disabled != "clothing",
            "include_items": disabled != "items",
            "include_underwear": False,
        },
    )
    assert response.status_code == 502, response.text
    assert await count_entities() == 0


async def test_valid_sixteen_item_limit_and_empty_outfit(auth_client, npc_world):
    value = draft()
    value["items"] = [item(f"Tool {i}") for i in range(16)]
    response = await auth_client.post(
        PATH + "/npc-with-items",
        json={
            "scene_id": "LAB",
            "creation_id": str(uuid4()),
            "draft": value,
        },
    )
    assert response.status_code == 200, response.text
    assert len(response.json()["item_ids"]) == 16
    value["items"] = []
    response = await auth_client.post(
        PATH + "/npc-with-items",
        json={
            "scene_id": "LAB",
            "creation_id": str(uuid4()),
            "draft": value,
        },
    )
    assert response.status_code == 200
    assert response.json()["item_ids"] == []


@pytest.mark.parametrize(
    "bad_result", ["not JSON", {"name": "Incomplete", "secret": "not-client-data"}]
)
async def test_invalid_model_results_do_not_publish_or_leak_details(
    auth_client, npc_world, monkeypatch, bad_result
):
    model(monkeypatch, bad_result)
    response = await auth_client.post(
        PATH + "/generate-npc-draft", json={"scene_id": "LAB", "brief": "A doctor"}
    )
    assert response.status_code == 502
    assert "not-client-data" not in response.text
    assert "NPC draft" in response.text
    assert await count_entities() == 0


async def test_create_links_owned_and_worn_items_and_preserves_export(auth_client, npc_world):
    payload = {"scene_id": "LAB", "creation_id": str(uuid4()), "draft": draft()}
    response = await auth_client.post(PATH + "/npc-with-items", json=payload)
    assert response.status_code == 200, response.text
    npc_id = response.json()["npc_id"]
    assert npc_id == npc_id.upper() and len(npc_id) <= 30
    assert all(
        identifier == identifier.upper() and len(identifier) <= 30
        for identifier in response.json()["item_ids"]
    )
    assert await count_entities() == 6
    async with TestSessionLocal() as db:
        rows = list(await db.scalars(select(WorldEntity)))
        npc = next(row for row in rows if row.id == npc_id)
        items = [row for row in rows if row.entity_type == "OBJECT"]
        assert set(npc.inventory) == {row.id for row in items}
        assert all(row.is_in_inventory and row.current_scene_id == "INVENTORY" for row in items)
        assert len(npc.visual_profile["worn"]) == 4
        visible = character_visuals(npc, canonical_inventory(npc.inventory, items), detailed=True)
        assert "White coat" in visible["clothing"]
        assert "Red bra" not in visible["clothing"]
        manifest = await AdventureExporter.build_full_manifest(db, "npc-draft-world")
        assert len(manifest["npcs"]) == 1 and len(manifest["objects"]) == 5
        assert manifest["npcs"][0]["visual_profile"] == npc.visual_profile
        adventure = await db.get(AdventureTemplate, "npc-draft-world")
        assert adventure.original_manifest["plot"] == "Keep this plot."
    retry = await auth_client.post(PATH + "/npc-with-items", json=payload)
    assert retry.status_code == 200 and retry.json()["npc_id"] == npc_id
    assert await count_entities() == 6
    payload["draft"]["name"] = "Changed after timeout"
    assert (await auth_client.post(PATH + "/npc-with-items", json=payload)).status_code == 409


@pytest.mark.parametrize("age", [None, 17])
async def test_inner_layers_reject_unknown_or_minor_owner_atomically(auth_client, npc_world, age):
    value = draft()
    value["age_years"] = age
    response = await auth_client.post(
        PATH + "/npc-with-items",
        json={
            "scene_id": "LAB",
            "creation_id": str(uuid4()),
            "draft": value,
        },
    )
    assert response.status_code == 400, response.text
    assert await count_entities() == 0


async def test_inner_flag_cannot_be_bypassed_and_latest_settings_are_checked(
    auth_client, npc_world
):
    value = draft()
    value["items"][1]["clothing"]["underwear"] = False
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, "npc-draft-world")
        adventure.original_manifest = {"clothing_settings": {"detailed": False}}
        await db.commit()
    response = await auth_client.post(
        PATH + "/npc-with-items",
        json={
            "scene_id": "LAB",
            "creation_id": str(uuid4()),
            "draft": value,
        },
    )
    assert response.status_code == 400
    assert await count_entities() == 0


@pytest.mark.parametrize(
    "change", ["duplicate", "worn-key", "invalid-coverage", "script", "too-many"]
)
async def test_invalid_bundles_do_not_write(auth_client, npc_world, change):
    value = draft()
    if change == "duplicate":
        value["items"].append(deepcopy(value["items"][0]))
    if change == "worn-key":
        value["items"][-1]["worn"] = True
    if change == "invalid-coverage":
        value["items"][0]["clothing"]["coverage"] = ["invalid"]
    if change == "script":
        value["script"] = "unexpected"
    if change == "too-many":
        value["items"] = [item(f"Key {i}") for i in range(17)]
    response = await auth_client.post(
        PATH + "/npc-with-items",
        json={
            "scene_id": "LAB",
            "creation_id": str(uuid4()),
            "draft": value,
        },
    )
    assert response.status_code == 422, response.text
    assert await count_entities() == 0


@pytest.mark.parametrize("endpoint", ["generate-npc-draft", "npc-with-items"])
async def test_other_adventure_or_deleted_scene_cannot_be_used(
    auth_client, npc_world, monkeypatch, endpoint
):
    call = model(monkeypatch, draft())
    payload = (
        {"brief": "A doctor", "scene_id": "MISSING"}
        if endpoint.startswith("generate")
        else {
            "scene_id": "MISSING",
            "creation_id": str(uuid4()),
            "draft": draft(),
        }
    )
    response = await auth_client.post(PATH + "/" + endpoint, json=payload)
    assert response.status_code == 400
    missing = PATH.replace("npc-draft-world", "other-world") + "/" + endpoint
    assert (await auth_client.post(missing, json=payload)).status_code == 404
    call.assert_not_called()
    assert await count_entities() == 0
