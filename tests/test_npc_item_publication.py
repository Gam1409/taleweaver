"""Command transfers persist through canonical owners and reject stale inventories."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.engine.clothing.context import actor_records
from backend.engine.clothing.visuals import session_objects
from backend.engine.narrated_items.commands import transfer
from backend.engine.narrated_items.persistence import publish_command
from backend.engine.scene_staging.props import KEY as PROPS_KEY
from backend.engine.visual_novel.continuity import possession_snapshot
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import seed_vn


async def frame(host):
    rows = await session_objects(host.db, host.game_id)
    return actor_records(host, rows), possession_snapshot(host, rows)


async def test_inline_item_can_be_put_down_reloaded_and_taken_with_the_same_id():
    async with TestSessionLocal() as db:
        _, avatar, state, _ = await seed_vn(db)
        host = SimpleNamespace(game_id=state.session_id, state=state, avatar=avatar, db=db)
        actors, snapshot = await frame(host)
        item = snapshot.items["HIDDEN_RING"]
        changed, _, receipt = transfer(
            actors,
            snapshot,
            "LINA",
            item["id"],
            "put_down",
            position="on the bench",
            detailed=False,
        )
        unrelated = {"item_id": "OTHER", "owner_id": "LINA", "spatial_position": "on another shelf"}
        state.entity_states = {
            **state.entity_states,
            PROPS_KEY: {
                "items": [
                    {"item_id": item["id"], "owner_id": "LINA", "spatial_position": "old position"},
                    unrelated,
                ]
            },
        }
        await publish_command(host, actors, snapshot, changed, receipt)
        assert state.entity_states[PROPS_KEY]["items"] == [unrelated]
        await db.commit()
        actors, snapshot = await frame(host)
        assert snapshot.owners[item["id"]] == "__scene__"
        assert snapshot.items[item["id"]]["name"] == item["name"]
        rows = list(
            await db.scalars(
                select(WorldEntity).where(
                    WorldEntity.session_id == state.session_id, WorldEntity.id == item["id"]
                )
            )
        )
        assert len(rows) == 1 and rows[0].spatial_position == "on the bench"
        taken, _, receipt = transfer(actors, snapshot, "LINA", item["id"], "take", detailed=False)
        await publish_command(host, actors, snapshot, taken, receipt)
        await db.commit()
        _, final = await frame(host)
        assert final.owners[item["id"]] == "LINA"
        assert rows[0].spatial_position is None


async def test_stale_actor_inventory_is_not_replaced_by_an_older_command_preview():
    async with TestSessionLocal() as db:
        _, avatar, state, _ = await seed_vn(db)
        host = SimpleNamespace(game_id=state.session_id, state=state, avatar=avatar, db=db)
        actors, snapshot = await frame(host)
        changed, _, receipt = transfer(
            actors, snapshot, "LINA", "HIDDEN_RING", "put_down", detailed=False
        )
        addition = {"id": "NEW_NOTE", "name": "A new note"}
        state.entity_states = {
            **state.entity_states,
            "LINA": {"inventory": [*actors["LINA"]["inventory"], addition]},
        }
        with pytest.raises(ValueError, match="changed"):
            await publish_command(host, actors, snapshot, changed, receipt)
        assert addition in state.entity_states["LINA"]["inventory"]
        assert not await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == state.session_id, WorldEntity.id == "HIDDEN_RING"
            )
        )
