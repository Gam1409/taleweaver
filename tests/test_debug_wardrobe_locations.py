"""Debug separates worn clothes, carried possessions and persistent room objects."""

import json
from copy import deepcopy

from sqlalchemy import select

from backend.engine.debug_engine import DebugEngine
from backend.engine.debug_npc_tools import wardrobe_info
from backend.engine.scene_staging import props
from backend.engine.visual_novel.continuity import SCENE, possession_snapshot
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import seed_vn


def request(operation, item="COAT", **fields):
    return "npc_wardrobe " + json.dumps(
        {"npc_id": "LINA", "item_id": item, "operation": operation, **fields}
    )


async def test_putting_clothes_on_the_bed_preserves_identity_and_owner_without_following_the_npc():
    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        state.is_debug_enabled = True
        npc = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
        coat = {
            "id": "COAT",
            "name": "Халат Мики",
            "description": "Белый медицинский халат.",
            "image_url": "/data/example-coat.png",
            "item_type": "WEARABLE",
            "clothing": {"layer": 3, "coverage": ["torso", "arms"]},
            "wearable_slots": ["Chest"],
        }
        pajama = {**deepcopy(coat), "id": "PAJAMA", "name": "Пижама"}
        state.entity_states = {
            **state.entity_states,
            "LINA": {
                "inventory": [coat, pajama],
                "visual_profile": {"appearance": {"age_years": 30}, "worn": [{"item_id": "COAT"}]},
            },
        }
        before_time = state.in_game_time
        result = await DebugEngine.handle_debug_command(
            db, state, request("place", spatial_position="на кровати"), user=user, avatar=avatar
        )
        assert "no longer carried or worn" in result, result
        await db.commit()
        await db.refresh(state)
        assert [row["id"] for row in state.entity_states["LINA"]["inventory"]] == ["PAJAMA"]
        assert not state.entity_states["LINA"]["visual_profile"]["worn"]
        entities = list(
            await db.scalars(select(WorldEntity).where(WorldEntity.session_id == state.session_id))
        )
        world = next(row for row in entities if row.id == "COAT")
        assert world.image_url == coat["image_url"]
        assert world.metadata_json["clothing"] == coat["clothing"]
        assert world.metadata_json["property_owner_id"] == "LINA"
        info = wardrobe_info(npc, entities, state.entity_states)
        assert [row["id"] for row in info["items"]] == ["PAJAMA"]
        assert info["items"][0]["worn"] is False
        assert [row["id"] for row in info["scene_items"]] == ["COAT"]
        assert info["scene_items"][0]["spatial_position"] == "на кровати"
        # The NPC leaves; the player's old room retains the visible garment.
        state.entity_states = {
            **state.entity_states,
            "LINA": {**state.entity_states["LINA"], "current_scene_id": "FOREST"},
        }
        placed = props.project(state, props.candidates(avatar, entities, state, set()))
        assert placed == [
            {
                "item_id": "COAT",
                "owner_id": "LINA",
                "name": coat["name"],
                "spatial_position": "на кровати",
            }
        ]
        state.current_scene_id = "FOREST"
        assert not props.project(state, props.candidates(avatar, entities, state, set()))
        state.current_scene_id = "START"
        snapshot = possession_snapshot(
            type("Host", (), {"state": state, "avatar": avatar})(), entities
        )
        assert (
            snapshot.owners["COAT"] == SCENE
            and snapshot.items["COAT"]["property_owner_id"] == "LINA"
        )
        # Returning and putting it on consumes the same room object, not a copy.
        state.entity_states = {
            **state.entity_states,
            "LINA": {**state.entity_states["LINA"], "current_scene_id": "START"},
        }
        result = await DebugEngine.handle_debug_command(
            db, state, request("wear"), user=user, avatar=avatar
        )
        assert "now worn" in result, result
        await db.commit()
        info = wardrobe_info(npc, entities, state.entity_states)
        assert not info["scene_items"]
        assert len([row for row in info["items"] if row["id"] == "COAT" and row["worn"]]) == 1
        assert not props.project(state, props.candidates(avatar, entities, state, set()))
        assert state.in_game_time == before_time


async def test_loose_clothes_owned_by_another_npc_cannot_be_taken_through_the_room_picker():
    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        state.is_debug_enabled = True
        other = await db.scalar(select(WorldEntity).where(WorldEntity.id == "ABSENT"))
        other.inventory = [{"id": "OTHER_COAT", "name": "Other coat"}]
        db.add(
            WorldEntity(
                id="OTHER_COAT",
                session_id=state.session_id,
                entity_type="OBJECT",
                name="Other coat",
                description="A coat.",
                current_scene_id="START",
                is_in_inventory=False,
                metadata_json={"clothing": {"layer": 3, "coverage": ["torso"]}},
            )
        )
        await db.commit()
        before = deepcopy(state.entity_states)
        result = await DebugEngine.handle_debug_command(
            db, state, request("wear", "OTHER_COAT"), user=user, avatar=avatar
        )
        assert "neither owned" in result
        assert state.entity_states == before and other.inventory[0]["id"] == "OTHER_COAT"


async def test_legacy_room_garment_without_metadata_remains_visible_for_repair():
    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        state.is_debug_enabled = True
        npc = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
        db.add(
            WorldEntity(
                id="OLD_COAT",
                session_id=state.session_id,
                entity_type="OBJECT",
                name="Old coat",
                description="A white coat.",
                item_type="WEARABLE",
                current_scene_id="START",
                is_hidden=False,
                is_in_inventory=False,
            )
        )
        await db.commit()
        entities = list(
            await db.scalars(select(WorldEntity).where(WorldEntity.session_id == state.session_id))
        )
        info = wardrobe_info(npc, entities, state.entity_states)
        assert (
            info["scene_items"][0]["id"] == "OLD_COAT"
            and info["scene_items"][0]["clothing"] is None
        )
        original = deepcopy(state.entity_states)
        result = await DebugEngine.handle_debug_command(
            db, state, request("wear", "OLD_COAT"), user=user, avatar=avatar
        )
        assert "valid garment metadata" in result and state.entity_states == original


async def test_a_stale_room_row_cannot_duplicate_a_garment_from_player_inventory():
    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        state.is_debug_enabled = True
        avatar.inventory = [*avatar.inventory, {"id": "PLAYER_COAT", "name": "Player coat"}]
        db.add(
            WorldEntity(
                id="PLAYER_COAT",
                session_id=state.session_id,
                entity_type="OBJECT",
                name="Player coat",
                description="A coat.",
                current_scene_id="START",
                is_in_inventory=False,
                metadata_json={"clothing": {"layer": 3, "coverage": ["torso"]}},
            )
        )
        await db.commit()
        original = deepcopy(state.entity_states)
        result = await DebugEngine.handle_debug_command(
            db, state, request("wear", "PLAYER_COAT"), user=user, avatar=avatar
        )
        assert "carried by the player" in result
        assert state.entity_states == original and avatar.inventory[-1]["id"] == "PLAYER_COAT"
