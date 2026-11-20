"""Real command capture binds persistent wardrobe facts to the saved input."""

from copy import deepcopy

from backend.engine.chpm.observable_state import capture as capture_views
from backend.engine.clothing.context import actor_records
from backend.engine.clothing.profiles import load_profile
from backend.engine.clothing.visuals import session_objects
from backend.engine.clothing.wear_provenance import command_matches
from backend.engine.npc_actions.contracts import Adjust, Take, Wear
from backend.engine.npc_actions.preparation import capture
from backend.engine.npc_actions.publication import publish
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_npc_action_publication import fixture


async def test_take_wear_and_adjust_preserve_identity_and_verifiable_input_after_reload():
    async with TestSessionLocal() as db:
        host, observed, _ = await fixture(db)
        db.add(
            WorldEntity(
                id="COAT",
                session_id=host.game_id,
                entity_type="OBJECT",
                name="Blue coat",
                description="A weatherproof blue coat.",
                current_scene_id=host.state.current_scene_id,
                is_hidden=False,
                is_in_inventory=False,
                is_portable=True,
                metadata_json={"clothing": {"layer": 2, "coverage": ["torso", "arms"]}},
            )
        )
        host.state.entity_states = {
            **host.state.entity_states,
            "LINA": {"visual_profile": {"version": 1, "worn": []}},
        }
        await db.commit()
        original_input = await db.get(ChatMessage, observed.message_id)
        before_inventory = deepcopy(host.avatar.inventory)
        views = await capture_views(host, ["LINA"], observed)
        draft = (await capture(host, views, observed))["LINA"]
        for request in [
            Take(tool="take_item", item_id="COAT"),
            Wear(tool="wear_item", item_id="COAT"),
            Adjust(tool="adjust_clothing", item_id="COAT", uncovered_regions=["arms"]),
        ]:
            assert draft.execute(request)["status"] == "staged"
        draft.approved = True
        assert [row["status"] for row in await publish(host, draft)] == ["applied"] * 3
        await db.commit()
        await db.refresh(host.state)
        actors = actor_records(host, await session_objects(db, host.game_id))
        profile = load_profile(actors["LINA"]["visual_profile"])
        coat = next(row for row in profile.worn if row.item_id == "COAT")
        assert coat.uncovered_regions == ["arms"]
        assert command_matches(coat.source, original_input, actor_id="LINA", item_id="COAT")
        assert coat.source.command.operation == "adjust_clothing"
        assert coat.source.command.input_hash == observed.content_hash
        assert coat.source.command.request_hash != observed.content_hash
        assert host.avatar.inventory == before_inventory
        assert "COAT" in {row["id"] for row in actors["LINA"]["resolved_inventory"]}
