"""A request for a controlled NPC cannot preapply that NPC's item acquisition."""

from copy import deepcopy

from backend.engine.clothing.visuals import session_objects
from backend.engine.visual_novel.continuity import SCENE, possession_snapshot
from tests.conftest import TestSessionLocal
from tests.test_npc_prepass_placements import apply, proof, setup


async def test_saved_loose_key_request_cannot_preapply_linas_inventory_acquisition():
    async with TestSessionLocal() as db:
        manager, _, _ = await setup(db)
        before = possession_snapshot(manager, await session_objects(db, manager.game_id))
        inventory = deepcopy(before.npcs["LINA"]["inventory"])
        inventory.append(deepcopy(before.items["BRASS_KEY"]))
        raw = {
            "updated_entities": [
                {
                    "entity_id": "LINA",
                    "inventory": inventory,
                    "movement_source": proof(),
                }
            ],
            "moved_entities": [
                {
                    "entity_id": "BRASS_KEY",
                    "to_scene_id": "START",
                    "movement_source": proof(),
                }
            ],
        }
        await apply(manager, raw)
        after = possession_snapshot(manager, await session_objects(db, manager.game_id))
        assert after.owners["BRASS_KEY"] == SCENE
        assert after.npcs["LINA"]["inventory"] == before.npcs["LINA"]["inventory"]
        assert after.owners == before.owners
