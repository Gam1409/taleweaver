"""Room reads reuse real directional routes, current locks and NPC movement policy."""

from copy import deepcopy
from types import SimpleNamespace

from sqlalchemy import select

from backend.engine.chpm import observable_scene
from backend.engine.scene_continuity.scope import SceneScope
from backend.models.world_entity import WorldEntity, WorldExit, WorldScene
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import seed_vn


async def test_route_read_uses_effective_lock_and_direction_without_revealing_secrets():
    async with TestSessionLocal() as db:
        _, avatar, state, _ = await seed_vn(db)
        npc = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
        npc.moveable = True
        db.add_all(
            [
                WorldScene(id=key, session_id=state.session_id, label=key, description="A room.")
                for key in ["OPEN", "LOCKED", "INCOMING"]
            ]
            + [
                WorldExit(
                    id="open",
                    session_id=state.session_id,
                    from_scene_id="START",
                    to_scene_id="OPEN",
                    label="Open door",
                ),
                WorldExit(
                    id="locked",
                    session_id=state.session_id,
                    from_scene_id="START",
                    to_scene_id="LOCKED",
                    label="Locked door",
                    is_locked=True,
                    code_to_unlock="PRIVATE_CODE",
                    on_open_exit_script="PRIVATE_SCRIPT",
                ),
                WorldExit(
                    id="incoming",
                    session_id=state.session_id,
                    from_scene_id="INCOMING",
                    to_scene_id="START",
                    label="Incoming",
                    exit_type="one_way",
                ),
            ]
        )
        await db.flush()
        host = SimpleNamespace(game_id=state.session_id, state=state, avatar=avatar, db=db)
        host._scene_continuity_scope = SceneScope("START", frozenset(), "Public room.", ())
        before = deepcopy(state.entity_states)
        view = observable_scene.project(host, await observable_scene.capture(host, [npc]), "LINA")
        routes = {row["scene_id"]: row for row in view["routes"]}
        assert set(routes) == {"OPEN", "LOCKED"}
        assert routes["OPEN"]["permitted"] is True
        assert routes["LOCKED"]["locked"] is True and routes["LOCKED"]["permitted"] is False
        assert view["description"] == "Public room."
        assert "PRIVATE" not in str(view) and state.entity_states == before
        npc.moveable = False
        immobile = observable_scene.project(
            host, await observable_scene.capture(host, [npc]), "LINA"
        )
        assert immobile["can_move"] is False
        assert all(row["permitted"] is False for row in immobile["routes"])


def test_route_context_for_another_observer_or_scene_is_unavailable():
    host = SimpleNamespace(state=SimpleNamespace(current_scene_id="room"))
    assert observable_scene.project(host, {"scene_id": "elsewhere"}, "npc") == {
        "routes_knowledge": "unavailable"
    }
    assert observable_scene.project(host, {"scene_id": "room", "actors": {"other": {}}}, "npc") == {
        "routes_knowledge": "unavailable"
    }
