"""Synthetic session-owned world for Living World retry and queue regressions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest_asyncio
from sqlalchemy import select

from backend.core.llm_router import GameMasterLLM
from backend.engine.living_world.schema import Settings, Simulation
from backend.models import (
    AdventureTemplate,
    Avatar,
    GameSession,
    SessionState,
    User,
    WorldEntity,
    WorldExit,
    WorldScene,
)


@pytest_asyncio.fixture
async def retry_world(auth_client, db_session, monkeypatch):
    owner = await db_session.scalar(select(User).where(User.username == "test_user"))
    template = AdventureTemplate(
        id="lw-retry-template",
        owner_id=owner.id,
        title="Archive routine",
        original_manifest={"start_scene_id": "A"},
    )
    db_session.add(template)
    await db_session.flush()
    avatar = Avatar(id="lw-avatar", user_id=owner.id, name="Keeper")
    db_session.add(avatar)
    await db_session.flush()
    game = GameSession(
        id="lw-session", user_id=owner.id, avatar_id=avatar.id, template_id=template.id
    )
    db_session.add(game)
    await db_session.flush()
    state = SessionState(
        session_id=game.id,
        user_id=owner.id,
        avatar_id=avatar.id,
        template_id=template.id,
        current_scene_id="A",
        in_game_time=0,
        entity_states={},
    )
    db_session.add(state)
    for identifier in ("A", "B", "C"):
        db_session.add(
            WorldScene(
                id=identifier,
                session_id=game.id,
                label=identifier,
                description="A quiet archive room.",
            )
        )
    for identifier in ("GUIDE", "PEER"):
        db_session.add(
            WorldEntity(
                id=identifier,
                session_id=game.id,
                entity_type="NPC",
                name=identifier.title(),
                description="A synthetic archive worker.",
                current_scene_id="A",
                moveable=True,
                movement_type="MOVABLE",
                allowed_scenes=["A", "B"],
                goal=f"Private goal for {identifier}",
                character="Patient and observant.",
            )
        )
    edge = WorldExit(
        id="archive-door",
        session_id=game.id,
        from_scene_id="A",
        to_scene_id="B",
        label="Door",
        exit_type="bidirectional",
        is_locked=False,
    )
    db_session.add(edge)
    await db_session.commit()
    inference = AsyncMock(
        side_effect=AssertionError("Rules and availability checks must not invoke inference")
    )
    monkeypatch.setattr(GameMasterLLM, "aexecute_simple_task", inference)
    return SimpleNamespace(
        db=db_session, state=state, edge=edge, session_id=game.id, inference=inference
    )


def simulation(events, **settings):
    return Simulation(
        settings=Settings(living_world_enabled=True, mode="CATCH_UP", **settings),
        target=10,
        events=events,
    )


async def actor(db, session_id, identifier="GUIDE"):
    return await db.scalar(
        select(WorldEntity).where(
            WorldEntity.session_id == session_id, WorldEntity.id == identifier
        )
    )


async def current_state(db, session_id):
    return await db.scalar(select(SessionState).where(SessionState.session_id == session_id))


async def configure_reverse_route(world, blocked):
    db, state, edge = world.db, world.state, world.edge
    state.entity_states = {"GUIDE": {"current_scene_id": "B"}}
    edge_changes = {
        "one_way": ("exit_type", "one_way"),
        "row_lock": ("is_locked", True),
        "exit_script": ("on_exit_used_script", "blocked"),
        "open_script": ("on_open_exit_script", "blocked"),
        "guard": ("unlock_expression", "blocked"),
        "rule": ("rule_to_unlock", "blocked"),
    }
    if blocked in edge_changes:
        field, value = edge_changes[blocked]
        setattr(edge, field, value)
    lock_keys = {"id_lock": edge.id, "stored_pair": "A:B", "reverse_pair": "B:A"}
    if blocked in lock_keys:
        state.exit_states = {lock_keys[blocked]: {"is_locked": True}}
    if blocked == "allowed":
        (await actor(db, world.session_id)).allowed_scenes = ["B"]
    scenes = {
        row.id: row
        for row in await db.scalars(
            select(WorldScene).where(WorldScene.session_id == world.session_id)
        )
    }
    script_changes = {
        "enter_script": (scenes["A"], "on_enter_scene_script"),
        "leave_script": (scenes["B"], "on_leave_scene_script"),
    }
    if blocked in script_changes:
        scene, field = script_changes[blocked]
        setattr(scene, field, "blocked")
    if blocked == "foreign":
        edge.session_id = None
        edge.template_id = state.template_id
    await db.commit()
    return scenes["B"]
