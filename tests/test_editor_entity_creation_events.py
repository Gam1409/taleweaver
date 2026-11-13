"""Create requests retain the same authored lifecycle contract as editor updates."""

from copy import deepcopy

import pytest
from sqlalchemy import select

from backend.engine.adventure_exporter import AdventureExporter
from backend.engine.adventure_importer import AdventureTemplateImporter
from backend.models.adventure_template import AdventureTemplate
from backend.models.user import User
from backend.models.world_entity import WorldEntity, WorldScene
from tests.conftest import TestSessionLocal
from tests.editor_entity_creation_support import entity_creation_world, entity_payload, event_fields

__all__ = ["entity_creation_world"]
pytestmark = pytest.mark.asyncio


async def _create(world, payload):
    response = await world.client.post(
        f"/api/adventures/{world.template_id}/editor/entity", json=payload
    )
    assert response.status_code == 200, response.text
    return response.json()["entity"]


@pytest.mark.parametrize("kind", ["NPC", "OBJECT"])
async def test_created_events_reload_edit_and_read_like_existing_updates(
    entity_creation_world, kind
):
    world = entity_creation_world
    payload = entity_payload(kind)
    created = await _create(world, payload)
    expected = event_fields(kind)
    assert {key: created["metadata_json"].get(key) for key in expected} == expected
    assert created["spatial_position"] == "beside the archive door"
    async with TestSessionLocal() as db:
        row = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.template_id == world.template_id,
                WorldEntity.session_id.is_(None),
                WorldEntity.id == payload["entity_id"],
            )
        )
        assert {key: row.metadata_json.get(key) for key in expected} == expected
        assert row.metadata_json["extension_data"] == {"enabled": True}
        assert row.spatial_position == "beside the archive door"
    edited = await world.client.patch(
        f"/api/adventures/{world.template_id}/editor/entity",
        json={
            "target_type": kind.lower(),
            "target_id": payload["entity_id"],
            "description": "Edited description.",
        },
    )
    assert edited.status_code == 200, edited.text
    assets = await world.client.get(f"/api/adventures/{world.template_id}/editor/assets")
    assert assets.status_code == 200, assets.text
    collection = "npcs" if kind == "NPC" else "objects"
    entity = next(row for row in assets.json()[collection] if row["id"] == payload["entity_id"])
    assert {key: entity["metadata_json"].get(key) for key in expected} == expected
    assert entity["spatial_position"] == "beside the archive door"


@pytest.mark.parametrize("kind", ["NPC", "OBJECT"])
@pytest.mark.parametrize("sent", ["omitted", "null", "clear"])
async def test_legacy_metadata_events_follow_existing_presence_rules(
    entity_creation_world, kind, sent
):
    world = entity_creation_world
    payload = entity_payload(kind)
    expected = event_fields(kind)
    payload = {key: value for key, value in payload.items() if key not in expected}
    payload["metadata_json"].update(expected)
    payload["legacy_extension"] = {"kept_by_client": True}
    if sent != "omitted":
        payload.update({key: None if sent == "null" else " \n " for key in expected})
    created = await _create(world, payload)
    expected = {key: "" for key in expected} if sent == "clear" else expected
    assert {key: created["metadata_json"].get(key) for key in expected} == expected
    assert created["metadata_json"]["extension_data"] == {"enabled": True}


@pytest.mark.parametrize("kind", ["NPC", "OBJECT"])
async def test_optional_events_and_position_keep_legacy_defaults(entity_creation_world, kind):
    world = entity_creation_world
    payload = {
        "entity_id": "PLAIN",
        "entity_type": kind,
        "scene_id": "HALL",
        "name": "Plain entity",
        "description": "No callbacks.",
    }
    created = await _create(world, payload)
    assert created["spatial_position"] is None
    assert not any(key in created["metadata_json"] for key in event_fields(kind))
    assert created["hp"] is None and created["stamina"] is None and created["mana"] is None


@pytest.mark.parametrize("kind", ["NPC", "OBJECT"])
async def test_position_uses_existing_update_normalization(entity_creation_world, kind):
    world = entity_creation_world
    payload = entity_payload(kind)
    payload["spatial_position"] = " " + "A" * 260 + " "
    created = await _create(world, payload)
    assert created["spatial_position"] == "A" * 255


async def test_owner_and_session_scopes_remain_authoritative(entity_creation_world):
    world = entity_creation_world
    async with TestSessionLocal() as db:
        other = User(id="other-author", username="other-author", hashed_password="synthetic")
        db.add(other)
        await db.flush()
        foreign = AdventureTemplate(id="foreign-template", title="Foreign", owner_id=other.id)
        db.add(foreign)
        await db.flush()
        db.add(WorldScene(id="HALL", template_id=foreign.id, label="Hall", description="A room."))
        saved = WorldEntity(
            id="COAT",
            template_id=world.template_id,
            session_id=world.ids["game_id"],
            entity_type="OBJECT",
            name="Saved coat",
            description="Saved state.",
            current_scene_id="HALL",
            metadata_json={"private_marker": "saved"},
        )
        db.add(saved)
        await db.commit()
    denied = await world.client.post(
        "/api/adventures/foreign-template/editor/entity", json=entity_payload("OBJECT")
    )
    assert denied.status_code == 404
    created = await _create(world, entity_payload("OBJECT"))
    assert "private_marker" not in created["metadata_json"]
    async with TestSessionLocal() as db:
        saved = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == world.ids["game_id"], WorldEntity.id == "COAT"
            )
        )
        assert saved.metadata_json == {"private_marker": "saved"}
        assert (
            await db.scalar(
                select(WorldEntity).where(WorldEntity.template_id == "foreign-template")
            )
            is None
        )


async def test_created_callbacks_survive_real_adventure_export_import(entity_creation_world):
    world = entity_creation_world
    for kind in ("OBJECT", "NPC"):
        await _create(world, entity_payload(kind))
    async with TestSessionLocal() as db:
        manifest = await AdventureExporter.build_full_manifest(db, world.template_id)
        manifest = deepcopy(manifest)
        manifest["title"] = "Imported lifecycle callbacks"
        manifest["adventure"]["title"] = manifest["title"]
        assert await AdventureTemplateImporter.import_adv_manifest(
            db, manifest, owner_id=world.user_id
        )
        imported = await db.scalar(
            select(AdventureTemplate).where(AdventureTemplate.title == manifest["title"])
        )
        assert imported is not None
        rows = list(
            await db.scalars(
                select(WorldEntity).where(
                    WorldEntity.template_id == imported.id, WorldEntity.session_id.is_(None)
                )
            )
        )
        for kind in ("NPC", "OBJECT"):
            entity = next(row for row in rows if row.entity_type == kind)
            expected = event_fields(kind)
            assert {key: entity.metadata_json.get(key) for key in expected} == expected
            assert entity.spatial_position == "beside the archive door"


@pytest.mark.parametrize(
    "requirements,expected",
    [
        (
            {"code_to_unlock": " 4862 ", "item_to_unlock": "spare key", "rule_to_unlock": " wait "},
            {"code_to_unlock": "4862", "item_to_unlock": "", "rule_to_unlock": ""},
        ),
        (
            {"code_to_unlock": " ", "item_to_unlock": "  brass key ", "rule_to_unlock": " wait "},
            {"code_to_unlock": "", "item_to_unlock": "BRASS_KEY", "rule_to_unlock": ""},
        ),
        (
            {"rule_to_unlock": "  ask the archivist  "},
            {"code_to_unlock": "", "item_to_unlock": "", "rule_to_unlock": "ask the archivist"},
        ),
    ],
)
async def test_container_creation_reuses_existing_edit_lock_normalization(
    entity_creation_world, requirements, expected
):
    world = entity_creation_world
    payload = entity_payload("OBJECT", "CHEST")
    payload.update(item_type="CONTAINER", is_portable=False)
    payload["metadata_json"].update(
        locked=True,
        unlock_expression="tw.vars.get('permission') == True",
        on_unlock_success_script="tw.vars.set('opened', True)",
        on_unlock_failure_text="Permission required.",
        **requirements,
    )
    created = await _create(world, payload)
    assert {key: created["metadata_json"].get(key) for key in expected} == expected
    assert created["is_portable"] is False
    assert created["metadata_json"]["locked"] is True
    assert created["metadata_json"]["unlock_expression"] == "tw.vars.get('permission') == True"
    assert created["metadata_json"]["on_unlock_failure_text"] == "Permission required."
    edit = await world.client.patch(
        f"/api/adventures/{world.template_id}/editor/entity",
        json={"target_type": "object", "target_id": "CHEST", "locked": True, **requirements},
    )
    assert edit.status_code == 200, edit.text
    async with TestSessionLocal() as db:
        row = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.template_id == world.template_id,
                WorldEntity.session_id.is_(None),
                WorldEntity.id == "CHEST",
            )
        )
        assert {key: row.metadata_json.get(key) for key in expected} == expected
