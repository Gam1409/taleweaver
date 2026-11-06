"""Checkpoint rewind restores canonical item records and the historical map together."""

from copy import deepcopy

import pytest
from sqlalchemy import select

from backend.engine.session_checkpoint_service import SessionCheckpointService
from backend.models.avatar import Avatar
from backend.models.session_checkpoint import SessionCheckpoint
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity
from backend.models.world_map import WorldMap
from tests.conftest import TestSessionLocal
from tests.test_item_repair import ITEM, PATH, chpm_world, portrait_world, repair_world

__all__ = ["chpm_world", "portrait_world", "repair_world"]
SID = "portrait-session"


async def checkpoint(db):
    saved = await SessionCheckpointService.create_checkpoint(db, SID, "MANUAL")
    await db.commit()
    return saved.id


async def restore(client, identifier):
    response = await client.post(f"/api/adventures/sessions/{SID}/checkpoints/{identifier}/restore")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("map_existed", [True, False])
async def test_map_rewind_drops_future_nodes_and_edges(auth_client, repair_world, map_existed):
    initial = {"TOWER": {"label": "Tower"}}
    async with TestSessionLocal() as db:
        if map_existed:
            db.add(
                WorldMap(
                    session_id=SID, nodes=deepcopy(initial), edges=[], current_scene_id="TOWER"
                )
            )
        identifier = await checkpoint(db)
        world = await db.scalar(select(WorldMap).where(WorldMap.session_id == SID))
        if world is None:
            world = WorldMap(session_id=SID, nodes={}, edges=[])
            db.add(world)
        world.nodes = {**initial, "FUTURE": {"label": "Future"}}
        world.edges = [{"from": "TOWER", "to": "FUTURE"}]
        state = await db.scalar(select(SessionState).where(SessionState.session_id == SID))
        state.current_scene_id = "FUTURE"
        state.discovered_scenes = ["TOWER", "FUTURE"]
        await db.commit()
    result = await restore(auth_client, identifier)
    assert result["warnings"] == []
    async with TestSessionLocal() as db:
        world = await db.scalar(select(WorldMap).where(WorldMap.session_id == SID))
        if map_existed:
            assert world.nodes == initial and world.edges == []
            assert world.current_scene_id == "TOWER"
        else:
            assert world is None or "FUTURE" not in world.nodes


async def test_repair_and_rewind_agree_on_canonical_item_description(auth_client, repair_world):
    async with TestSessionLocal() as db:
        identifier = await checkpoint(db)
    before = await auth_client.get(PATH)
    assert before.status_code == 200
    repaired = await auth_client.post(
        PATH + "/apply",
        json={
            "before_hash": before.json()["before_hash"],
            "parts": ["text"],
            "values": {"name": "Repaired coat", "description": "A revised description."},
        },
    )
    assert repaired.status_code == 200, repaired.text
    result = await restore(auth_client, identifier)
    assert result["warnings"] == []
    async with TestSessionLocal() as db:
        canonical = await db.scalar(
            select(WorldEntity).where(WorldEntity.session_id == SID, WorldEntity.id == "COAT")
        )
        state = await db.scalar(select(SessionState).where(SessionState.session_id == SID))
        assert canonical.description == ITEM["description"]
        assert canonical.name == ITEM["name"]
        assert state.entity_states["NPC_NEW"]["inventory"][0]["description"] == ITEM["description"]
        assert canonical.metadata_json["script_marker"] == "keep"


async def test_old_checkpoint_filters_the_map_without_touching_other_sessions(
    auth_client, repair_world
):
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == SID))
        state.discovered_scenes = ["TOWER"]
        db.add(
            WorldMap(
                session_id=SID,
                nodes={"TOWER": {"label": "Tower"}, "FUTURE": {}},
                edges=[{"from": "TOWER", "to": "FUTURE"}],
                current_scene_id="FUTURE",
            )
        )
        db.add(WorldMap(session_id="other-session", nodes={"PRIVATE": {}}, edges=[]))
        identifier = await checkpoint(db)
        saved = await db.get(SessionCheckpoint, identifier)
        snapshot = deepcopy(saved.state_snapshot)
        snapshot.pop("world_map", None)
        snapshot.pop("canonical_items", None)
        saved.state_snapshot = snapshot
        await db.commit()
    result = await restore(auth_client, identifier)
    assert len(result["warnings"]) == 1 and "older checkpoint" in result["warnings"][0]
    async with TestSessionLocal() as db:
        world = await db.scalar(select(WorldMap).where(WorldMap.session_id == SID))
        other = await db.scalar(select(WorldMap).where(WorldMap.session_id == "other-session"))
        assert set(world.nodes) == {"TOWER"} and world.edges == []
        assert other.nodes == {"PRIVATE": {}}


async def test_invalid_world_snapshot_is_rejected_before_in_memory_state_changes(
    auth_client, repair_world
):
    async with TestSessionLocal() as db:
        identifier = await checkpoint(db)
        state = await db.scalar(select(SessionState).where(SessionState.session_id == SID))
        avatar = await db.get(Avatar, state.avatar_id)
        avatar.hp = 7
        state.current_scene_id = "FUTURE"
        saved = await db.get(SessionCheckpoint, identifier)
        saved.state_snapshot = {**saved.state_snapshot, "canonical_items": [{"id": "COAT"}]}
        await db.flush()
        with pytest.raises(ValueError, match="canonical item checkpoint"):
            await SessionCheckpointService.restore_checkpoint(db, SID, identifier)
        assert avatar.hp == 7 and state.current_scene_id == "FUTURE"
