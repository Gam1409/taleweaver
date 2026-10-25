"""Dynamic topology survives saves and remains isolated from templates and other users."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import select

from backend.engine.dynamic_locations import images
from backend.engine.dynamic_locations.schema import registry, save_registry
from backend.engine.dynamic_locations.service import discard_unentered
from backend.engine.session_checkpoint_service import SessionCheckpointService
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldExit, WorldScene
from backend.models.world_map import WorldMap
from tests.conftest import TestSessionLocal
from tests.test_dynamic_locations import apply, decision
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]


async def seed():
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        save_registry(state, {"policy": {"enabled": True, "generate_images": False}})
        db.add(
            WorldScene(id="TOWER", session_id="portrait-session", label="Лес", description="Лес")
        )
        db.add(
            WorldMap(
                session_id="portrait-session",
                current_scene_id="TOWER",
                nodes={"TOWER": {"label": "Лес"}},
                edges=[],
            )
        )
        await db.commit()
        checkpoint = await SessionCheckpointService.create_checkpoint(
            db, "portrait-session", "manual"
        )
        await db.commit()
        checkpoint_id = checkpoint.id
        manager = SimpleNamespace(db=db, state=state, game_id=state.session_id)
        new_id = await apply(manager, decision())
        state.current_scene_id = new_id
        world = await db.scalar(select(WorldMap).where(WorldMap.session_id == state.session_id))
        world.nodes = {**world.nodes, new_id: {"label": "Таверна"}}
        world.edges = [{"from": "TOWER", "to": new_id}]
        world.current_scene_id = new_id
        await db.commit()
        return new_id, checkpoint_id


async def test_copy_export_import_keep_parent_ids_and_connections(auth_client, portrait_world):
    scene_id, _ = await seed()
    copied = await auth_client.post("/api/adventures/sessions/portrait-session/copy")
    assert copied.status_code == 201, copied.text
    exported = await auth_client.get("/api/adventures/sessions/portrait-session/export")
    assert exported.status_code == 200, exported.text
    imported = await auth_client.post(
        "/api/adventures/sessions/import",
        files={"file": ("places.ads", exported.content, "application/zip")},
    )
    assert imported.status_code == 200, imported.text
    async with TestSessionLocal() as db:
        for sid in (copied.json()["game_id"], imported.json()["game_id"]):
            state = await db.scalar(select(SessionState).where(SessionState.session_id == sid))
            assert registry(state)["places"][scene_id]["parent_id"] == "TOWER"
            assert state.current_scene_id == scene_id
            scene = await db.scalar(
                select(WorldScene).where(WorldScene.session_id == sid, WorldScene.id == scene_id)
            )
            assert scene.label == "Таверна"
            exit_row = await db.scalar(
                select(WorldExit).where(
                    WorldExit.session_id == sid, WorldExit.to_scene_id == scene_id
                )
            )
            assert exit_row.exit_type == "bidirectional"
        assert not list(
            (
                await db.scalars(
                    select(WorldScene).where(
                        WorldScene.session_id.is_(None), WorldScene.id == scene_id
                    )
                )
            ).all()
        )


async def test_restore_removes_future_scene_exits_and_map_nodes(auth_client, portrait_world):
    scene_id, checkpoint = await seed()
    async with TestSessionLocal() as db:
        await SessionCheckpointService.restore_checkpoint(db, "portrait-session", checkpoint)
        await db.commit()
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        assert state.current_scene_id == "TOWER"
        assert not registry(state).get("places")
        assert await db.scalar(select(WorldScene).where(WorldScene.id == scene_id)) is None
        assert await db.scalar(select(WorldExit).where(WorldExit.to_scene_id == scene_id)) is None
        world = await db.scalar(select(WorldMap).where(WorldMap.session_id == state.session_id))
        assert scene_id not in world.nodes
        assert world.edges == []
        assert world.current_scene_id == "TOWER"


async def test_policy_and_image_retry_are_owner_scoped(auth_client, portrait_world, monkeypatch):
    scene_id, _ = await seed()
    base = "/api/adventures/portrait-session/dynamic-locations"
    assert (await auth_client.get(base)).json()["count"] == 1
    result = await auth_client.patch(
        base, json={"enabled": True, "scale": "building", "generate_images": False}
    )
    assert result.status_code == 200
    assert (await auth_client.get(base)).json()["policy"]["scale"] == "building"
    assert (
        await auth_client.get("/api/adventures/other-session/dynamic-locations")
    ).status_code == 404
    assert (
        await auth_client.patch(
            "/api/adventures/other-session/dynamic-locations", json={"enabled": True}
        )
    ).status_code == 404
    assert (
        await auth_client.post(f"/api/adventures/other-session/dynamic-locations/{scene_id}/image")
    ).status_code == 404
    assert (await auth_client.post(base + "/TOWER/image")).status_code == 404
    scheduled = []
    monkeypatch.setattr(images, "schedule", lambda *args: scheduled.append(args))
    assert (await auth_client.post(base + f"/{scene_id}/image")).status_code == 200
    assert scheduled[0][1] == scene_id


async def test_unentered_provisional_location_is_removed(portrait_world):
    scene_id, _ = await seed()
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        state.current_scene_id = "TOWER"
        manager = SimpleNamespace(
            db=db, state=state, game_id=state.session_id, _dynamic_scene_images=[scene_id]
        )
        await discard_unentered(manager)
        await db.commit()
        assert not registry(state).get("places")
        assert await db.scalar(select(WorldScene).where(WorldScene.id == scene_id)) is None


async def test_image_completion_does_not_resurrect_rewound_scene(portrait_world, monkeypatch):
    scene_id, checkpoint = await seed()

    async def render(**_kwargs):
        async with TestSessionLocal() as db:
            await SessionCheckpointService.restore_checkpoint(db, "portrait-session", checkpoint)
            await db.commit()
        return "/data/background.png"

    monkeypatch.setattr(images.database, "AsyncSessionLocal", TestSessionLocal)
    monkeypatch.setattr(
        images,
        "_settings",
        AsyncMock(
            return_value=(
                {"advanced_model_provider": "stable_diffusion", "advanced_model": "test"},
                "",
                "",
            )
        ),
    )
    monkeypatch.setattr(images.MediaEngine, "generate_image", render)
    async with TestSessionLocal() as db:
        session = await db.get(GameSession, "portrait-session")
        owner = session.user_id
    await images._generate("portrait-session", scene_id, owner)
    async with TestSessionLocal() as db:
        assert await db.scalar(select(WorldScene).where(WorldScene.id == scene_id)) is None


async def test_background_updates_only_the_saved_scene(portrait_world, monkeypatch):
    scene_id, _ = await seed()
    monkeypatch.setattr(images.database, "AsyncSessionLocal", TestSessionLocal)
    async with TestSessionLocal() as db:
        session = await db.get(GameSession, "portrait-session")
        owner = session.user_id
    await images._generate("portrait-session", scene_id, owner)
    assert portrait_world[0]["provider_options"]["visual_target_type"] == "scene"
    assert "/sessions/portrait-session/" in str(portrait_world[0]["target_dir"])
    async with TestSessionLocal() as db:
        scene = await db.scalar(
            select(WorldScene).where(
                WorldScene.session_id == "portrait-session", WorldScene.id == scene_id
            )
        )
        assert scene.image_url.startswith("/data/")
