"""Deleting authored scenes remains durable across editor repair and portability."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.core.adventure_format import CURRENT_VERSION
from backend.models import (
    AdventureTemplate,
    Avatar,
    GameSession,
    User,
    WorldEntity,
    WorldExit,
    WorldScene,
)
from tests.conftest import TestSessionLocal


@pytest.fixture(autouse=True)
def no_media_writes(monkeypatch):
    monkeypatch.setattr("backend.engine.media_engine.MediaEngine.ensure_thumbnails", AsyncMock())
    monkeypatch.setattr(
        "backend.engine.media_engine.MediaEngine.generate_placeholder",
        AsyncMock(return_value="/data/placeholder.svg"),
    )


def _manifest(title, count):
    scenes = [f"ROOM_{index}" for index in range(count)]
    return {
        "format": "TaleWeaver",
        "version": CURRENT_VERSION,
        "title": title,
        "adventure": {"title": title, "image_url": "/data/placeholder.svg"},
        "start_scene_id": scenes[0] if scenes else None,
        "protagonist": {"name": "Hero", "starting_inventory": ["TOKEN"]},
        "sequences": [{"id": "CH1", "title": "Chapter", "order": 1, "exp_reward": 0}],
        "scenes": [
            {"id": scene, "name": scene, "description": "A quiet room."} for scene in scenes
        ],
        "exits": [
            {
                "from_scene_id": left,
                "to_scene_id": right,
                "label": "Door",
                "is_bidirectional": False,
            }
            for left, right in zip(scenes, scenes[1:], strict=False)
        ],
        "npcs": [
            {
                "id": f"NPC_{index}",
                "name": f"Guide {index}",
                "description": "A guide.",
                "start_scene_id": scene,
            }
            for index, scene in enumerate(scenes)
        ],
        "objects": [
            {
                "id": f"OBJECT_{index}",
                "name": f"Object {index}",
                "description": "A token.",
                "start_scene_id": scene,
            }
            for index, scene in enumerate(scenes)
        ]
        + [
            {
                "id": "TOKEN",
                "name": "Carried token",
                "description": "A carried token.",
                "start_scene_id": "INVENTORY",
            }
        ],
    }


async def _create(client, origin, count):
    from backend.engine.world_generator import WorldGenerator

    manifest = _manifest(f"Scene deletion {origin} {count}", count)
    if origin == "imported":
        result = await client.post("/api/adventures/import", json=deepcopy(manifest))
        assert result.status_code == 201, result.text
        return result.json()["adventure_id"]
    async with TestSessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == "test_user"))
        adventure = AdventureTemplate(
            title=manifest["title"],
            owner_id=user.id,
            original_manifest=deepcopy(manifest),
            is_ready=True,
            creation_status="Ready",
        )
        db.add(adventure)
        await db.flush()
        await WorldGenerator.apply_manifest(db, adventure.id, deepcopy(manifest))
        await db.commit()
        return adventure.id


async def _seed_independent_worlds(template_id):
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, template_id)
        other = AdventureTemplate(
            id="unrelated", title="Unrelated story", owner_id=adventure.owner_id
        )
        avatar = Avatar(id="saved-avatar", user_id=adventure.owner_id, name="Saved hero")
        db.add_all([other, avatar])
        await db.flush()
        db.add(
            GameSession(
                id="saved-world",
                user_id=adventure.owner_id,
                avatar_id=avatar.id,
                template_id=template_id,
            )
        )
        await db.flush()
        for scope in (
            {"template_id": "unrelated"},
            {"template_id": template_id, "session_id": "saved-world"},
        ):
            db.add_all(
                [
                    WorldScene(
                        id="ROOM_0",
                        label="Preserved room",
                        description="An independent room.",
                        **scope,
                    ),
                    WorldEntity(
                        id="NPC_0",
                        name="Preserved guide",
                        description="A guide.",
                        entity_type="NPC",
                        current_scene_id="ROOM_0",
                        **scope,
                    ),
                    WorldEntity(
                        id="OBJECT_0",
                        name="Preserved token",
                        description="A token.",
                        entity_type="OBJECT",
                        current_scene_id="ROOM_0",
                        **scope,
                    ),
                    WorldExit(
                        from_scene_id="ROOM_0", to_scene_id="OTHER", label="Preserved exit", **scope
                    ),
                ]
            )
        await db.commit()


async def _rows(template_id, model):
    async with TestSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(model).where(
                        model.template_id == template_id, model.session_id.is_(None)
                    )
                )
            ).all()
        )


async def _assert_world(client, template_id, remaining):
    expected_scenes = {f"ROOM_{index}" for index in remaining}
    expected_npcs = {f"NPC_{index}" for index in remaining}
    expected_objects = {f"OBJECT_{index}" for index in remaining} | {"TOKEN"}
    for _ in range(2):
        result = await client.get(f"/api/adventures/{template_id}/editor/assets")
        assert result.status_code == 200, result.text
        payload = result.json()
        assert {scene["id"] for scene in payload["scenes"]} == expected_scenes
        assert {npc["id"] for npc in payload["npcs"]} == expected_npcs
        assert {item["id"] for item in payload["objects"]} == expected_objects
        assert all(
            exit_row["from_scene_id"] in expected_scenes
            and exit_row["to_scene_id"] in expected_scenes
            for exit_row in payload["exits"]
        )
    assert {scene.id for scene in await _rows(template_id, WorldScene)} == expected_scenes
    entities = await _rows(template_id, WorldEntity)
    assert {entity.id for entity in entities} == expected_npcs | expected_objects


async def _assert_other_worlds():
    assert len(await _rows("unrelated", WorldScene)) == 1
    assert len(await _rows("unrelated", WorldEntity)) == 2
    assert len(await _rows("unrelated", WorldExit)) == 1
    async with TestSessionLocal() as db:
        for model, count in ((WorldScene, 1), (WorldEntity, 2), (WorldExit, 1)):
            assert (
                len(list(await db.scalars(select(model).where(model.session_id == "saved-world"))))
                == count
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["generated", "imported"])
@pytest.mark.parametrize("count", [1, 3])
async def test_delete_last_scene_stays_empty_after_refresh_reload_copy_and_import(
    auth_client, origin, count
):
    template_id = await _create(auth_client, origin, count)
    await _seed_independent_worlds(template_id)
    for index in range(count):
        deleted = await auth_client.delete(
            f"/api/adventures/{template_id}/editor/scene/ROOM_{index}"
        )
        assert deleted.status_code == 200, deleted.text
        assert f"ROOM_{index}" not in {scene.id for scene in await _rows(template_id, WorldScene)}
        await _assert_world(auth_client, template_id, range(index + 1, count))
    await _assert_other_worlds()
    for format_name in ("manifest", "adv"):
        exported = await auth_client.get(f"/api/adventures/{template_id}/export/{format_name}")
        assert exported.status_code == 200, exported.text
        assert (
            exported.json()["scenes"] == exported.json()["exits"] == exported.json()["npcs"] == []
        )
        assert {item["id"] for item in exported.json()["objects"]} == {"TOKEN"}
    copied = await auth_client.post(
        f"/api/adventures/{template_id}/duplicate", json={"title": "Empty copied world"}
    )
    assert copied.status_code == 201, copied.text
    await _assert_world(auth_client, copied.json()["id"], [])
    portable = exported.json()
    portable["adventure"]["title"] = "Empty imported world"
    portable["title"] = "Empty imported world"
    imported = await auth_client.post("/api/adventures/import", json=portable)
    assert imported.status_code == 201, imported.text
    await _assert_world(auth_client, imported.json()["adventure_id"], [])


@pytest.mark.asyncio
async def test_genuine_manifest_only_world_still_materializes_once(auth_client, monkeypatch):
    from backend.engine.world_generator import WorldGenerator

    manifest = _manifest("Lazy authoring world", 2)
    async with TestSessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == "test_user"))
        adventure = AdventureTemplate(
            title=manifest["title"], owner_id=user.id, original_manifest=manifest, is_ready=True
        )
        db.add(adventure)
        await db.commit()
        template_id = adventure.id
    apply = AsyncMock(wraps=WorldGenerator.apply_manifest)
    monkeypatch.setattr(WorldGenerator, "apply_manifest", apply)
    await _assert_world(auth_client, template_id, range(2))
    apply.assert_awaited_once()


@pytest.mark.asyncio
async def test_original_and_newly_authored_scenes_never_reappear_after_final_deletion(auth_client):
    template_id = await _create(auth_client, "generated", 1)
    added = await auth_client.post(
        f"/api/adventures/{template_id}/editor/scene",
        json={"scene_id": "AUTHORED", "label": "Authored room", "description": "A new room."},
    )
    assert added.status_code == 200, added.text
    for scene_id in ("ROOM_0", "AUTHORED"):
        deleted = await auth_client.delete(f"/api/adventures/{template_id}/editor/scene/{scene_id}")
        assert deleted.status_code == 200, deleted.text
        if scene_id == "ROOM_0":
            refreshed = await auth_client.get(f"/api/adventures/{template_id}/editor/assets")
            assert {scene["id"] for scene in refreshed.json()["scenes"]} == {"AUTHORED"}
            portable = await auth_client.get(f"/api/adventures/{template_id}/export/manifest")
            assert {scene["id"] for scene in portable.json()["scenes"]} == {"AUTHORED"}
    await _assert_world(auth_client, template_id, [])


@pytest.mark.asyncio
async def test_deleting_final_scene_prunes_stale_topology_from_older_edits(auth_client):
    template_id = await _create(auth_client, "generated", 3)
    async with TestSessionLocal() as db:
        original = deepcopy((await db.get(AdventureTemplate, template_id)).original_manifest)
    for index in range(3):
        if index:
            async with TestSessionLocal() as db:
                adventure = await db.get(AdventureTemplate, template_id)
                adventure.original_manifest = deepcopy(original)
                await db.commit()
        deleted = await auth_client.delete(
            f"/api/adventures/{template_id}/editor/scene/ROOM_{index}"
        )
        assert deleted.status_code == 200, deleted.text
    await _assert_world(auth_client, template_id, [])


@pytest.mark.asyncio
async def test_raw_manifest_backfills_authored_item_location_without_session_override(auth_client):
    template_id = await _create(auth_client, "generated", 2)
    await _seed_independent_worlds(template_id)
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, template_id)
        manifest = deepcopy(adventure.original_manifest)
        item = next(item for item in manifest["objects"] if item["id"] == "OBJECT_0")
        item.pop("start_scene_id", None)
        item.pop("current_scene_id", None)
        adventure.original_manifest = manifest
        private_item = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == "saved-world", WorldEntity.id == "OBJECT_0"
            )
        )
        private_item.current_scene_id = "ROOM_1"
        await db.commit()
    for _ in range(2):
        exported = await auth_client.get(f"/api/adventures/{template_id}/export/manifest")
        assert exported.status_code == 200, exported.text
        exported_item = next(
            item for item in exported.json()["objects"] if item["id"] == "OBJECT_0"
        )
        assert exported_item["start_scene_id"] == "ROOM_0"
        assert {
            (edge["from_scene_id"], edge["to_scene_id"]) for edge in exported.json()["exits"]
        } == {("ROOM_0", "ROOM_1")}
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, template_id)
        stored_item = next(
            item for item in adventure.original_manifest["objects"] if item["id"] == "OBJECT_0"
        )
        assert "start_scene_id" not in stored_item and "current_scene_id" not in stored_item
        private_item = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == "saved-world", WorldEntity.id == "OBJECT_0"
            )
        )
        assert private_item.current_scene_id == "ROOM_1"


@pytest.mark.asyncio
async def test_explicitly_empty_authoring_manifest_does_not_trigger_materialization(
    auth_client, monkeypatch
):
    from backend.engine.world_generator import WorldGenerator

    async with TestSessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == "test_user"))
        adventure = AdventureTemplate(
            title="Empty authoring world",
            owner_id=user.id,
            original_manifest={"scenes": [], "npcs": [], "objects": [], "exits": []},
        )
        db.add(adventure)
        await db.commit()
        template_id = adventure.id
    apply = AsyncMock(side_effect=AssertionError("Explicitly empty worlds must remain empty"))
    monkeypatch.setattr(WorldGenerator, "apply_manifest", apply)
    for _ in range(2):
        result = await auth_client.get(f"/api/adventures/{template_id}/editor/assets")
        assert result.status_code == 200, result.text
        assert result.json()["scenes"] == result.json()["entities_all"] == []
    apply.assert_not_awaited()
