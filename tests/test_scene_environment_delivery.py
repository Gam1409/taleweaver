"""Current public room facts survive capture and reach the visual atom inventory."""

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.engine.location_context import build_location_context
from backend.engine.scene_illustrations.snapshots import registry_of
from backend.engine.scene_illustrations.visual_plan import inventory
from backend.engine.visual_novel.runtime import capture_completed_moment
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity, WorldScene
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import seed_vn


@pytest.mark.parametrize("detail", ["full", "concise"])
def test_current_object_notes_reach_narrator(detail):
    scene = SimpleNamespace(id="LAB", label="Lab", description="A room", decorative_objects=[])
    kettle = SimpleNamespace(
        id="KETTLE",
        name="Kettle",
        entity_type="OBJECT",
        item_type="DEFAULT",
        description="A brass kettle",
        spatial_position="on table",
        notes="Currently boiling",
    )
    assert "Currently boiling" in build_location_context(scene, [kettle], [], detail)


async def test_frozen_room_objects_and_decor_reach_plan_without_private_contents():
    async with TestSessionLocal() as db:
        _, avatar, state, _ = await seed_vn(db)
        scene = await db.scalar(select(WorldScene).where(WorldScene.id == "START"))
        scene.decorative_objects = ["A geometric stained-glass ceiling"]
        for identifier, hidden, contained in [
            ("SCOPE", False, False),
            ("SECRET", True, False),
            ("BAG", False, True),
        ]:
            db.add(
                WorldEntity(
                    id=identifier,
                    session_id=state.session_id,
                    entity_type="OBJECT",
                    name=identifier,
                    description=f"{identifier} silver microscope",
                    current_scene_id="START",
                    spatial_position="on the oak workbench",
                    is_hidden=hidden,
                    is_in_inventory=contained,
                )
            )
        reply = ChatMessage(
            id="ROOM_REPLY", session_id=state.session_id, role="assistant", content="Lina nods."
        )
        db.add(reply)
        await db.flush()
        await capture_completed_moment(SimpleNamespace(db=db, avatar=avatar, state=state), reply)
        facts = registry_of(state.entity_states)["snapshots"][reply.id]["visible_facts"]
        encoded = json.dumps(facts)
        assert "SCOPE silver microscope" in encoded
        assert "stained-glass ceiling" in encoded
        assert "SECRET silver microscope" not in encoded
        assert "BAG silver microscope" not in encoded
        atoms = inventory(facts)
        assert any("SCOPE silver microscope" in str(atom.value) for atom in atoms)
        assert any("stained-glass ceiling" in str(atom.value) for atom in atoms)
        scene.decorative_objects = ["Future ceiling"]
        assert "Future ceiling" not in json.dumps(
            registry_of(state.entity_states)["snapshots"][reply.id]
        )
