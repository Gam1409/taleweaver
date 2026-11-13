"""Generated initial sessions own one independent copy of the authored protagonist."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.adventure_creation import create_adventure_records
from backend.api.routes.adventures.schemas import CreateAdventureTemplatePayload
from backend.api.routes.adventures.session_materializer import (
    materialize_initial_session_from_template,
)
from backend.engine.manifest_apply.avatar import persist_avatar
from backend.engine.manifest_apply.context import ApplyContext
from backend.engine.template_avatar import get_template_avatar
from backend.models.avatar import Avatar
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldScene
from tests.test_template_avatar_isolation import (
    _add_blueprint,
    _avatar_values,
    _manifest_protagonist,
    avatar_world,
)

__all__ = ["avatar_world"]
pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("shared", [False, True])
async def test_initial_materializer_uses_authored_blueprint_with_session_owner(
    avatar_world, monkeypatch, shared
):
    world = avatar_world
    monkeypatch.setattr(
        "backend.engine.manifest_apply.avatar._portrait", AsyncMock(return_value=None)
    )
    ctx = ApplyContext(world.db, world.template.id, {}, world.owner, world.template)
    authored, _ = await persist_avatar(ctx, _manifest_protagonist())
    if shared:
        world.template.owner_id = None
        authored.user_id = world.characters[0].user_id
    await world.db.commit()
    placeholder = deepcopy(_avatar_values(world.characters[1]))
    await materialize_initial_session_from_template(world.db, world.template.id, "saved-game-1")
    await world.db.commit()
    session = await world.db.get(GameSession, "saved-game-1")
    avatar = await world.db.get(Avatar, session.avatar_id)
    assert avatar.id != authored.id
    assert avatar.user_id == session.user_id
    assert avatar.name == authored.name
    assert avatar.description == authored.description
    assert avatar.template_id is None
    await world.db.refresh(world.characters[1])
    assert _avatar_values(world.characters[1]) == placeholder
    assert world.characters[1].template_id is None


async def test_repeated_materialization_preserves_independent_session_progress(avatar_world):
    world = avatar_world
    await materialize_initial_session_from_template(world.db, world.template.id, "saved-game-1")
    await world.db.commit()
    session = await world.db.get(GameSession, "saved-game-1")
    avatar = await world.db.get(Avatar, session.avatar_id)
    avatar.name = "Played session character"
    avatar.hp = 37
    avatar.inventory = [{"id": "FOUND_ITEM", "name": "Found during play"}]
    await world.db.commit()
    previous = deepcopy(_avatar_values(avatar))
    previous_id = avatar.id

    await materialize_initial_session_from_template(world.db, world.template.id, "saved-game-1")
    await world.db.commit()
    await world.db.refresh(session)
    assert session.avatar_id == previous_id
    await world.db.refresh(avatar)
    assert _avatar_values(avatar) == previous


async def test_historical_materialized_session_keeps_linked_played_character(avatar_world):
    world = avatar_world
    await _add_blueprint(world)
    world.db.add(
        WorldScene(
            id="PLAYED_ROOM", session_id="saved-game-1", label="Played room", description="A room"
        )
    )
    await world.db.commit()
    previous = deepcopy(_avatar_values(world.characters[1]))

    await materialize_initial_session_from_template(world.db, world.template.id, "saved-game-1")
    await world.db.commit()
    session = await world.db.get(GameSession, "saved-game-1")
    assert session.avatar_id == world.characters[1].id
    await world.db.refresh(world.characters[1])
    assert _avatar_values(world.characters[1]) == previous


async def test_materialized_equipment_is_independent_of_authored_blueprint(avatar_world):
    world = avatar_world
    authored = await _add_blueprint(world)
    await materialize_initial_session_from_template(world.db, world.template.id, "saved-game-1")
    session = await world.db.get(GameSession, "saved-game-1")
    avatar = await world.db.get(Avatar, session.avatar_id)
    avatar.equipment["MainHand"]["name"] = "Changed during play"
    assert authored.equipment["MainHand"]["name"] == "Authored compass"


async def test_creation_keeps_response_blueprint_separate_from_initial_session(avatar_world):
    world = avatar_world
    created = await create_adventure_records(
        world.db,
        CreateAdventureTemplatePayload(
            title="Independent initial protagonist",
            avatar_name="Authored hero",
            skip_generation=True,
        ),
        world.owner,
    )
    assert created.session.avatar_id != created.avatar.id
    assert await get_template_avatar(world.db, created.template.id) is created.avatar
    session_avatar = await world.db.get(Avatar, created.session.avatar_id)
    assert session_avatar.user_id == created.session.user_id
    assert session_avatar.name == created.avatar.name == "Authored hero"
    session_avatar.description = "Changed during the initial session"
    assert created.avatar.description == "A mysterious wanderer..."


async def test_real_manifest_persistence_keeps_created_blueprint_id_and_saved_isolation(
    avatar_world, monkeypatch
):
    world = avatar_world
    created = await create_adventure_records(
        world.db,
        CreateAdventureTemplatePayload(title="Generated protagonist", skip_generation=True),
        world.owner,
    )
    response_avatar_id = created.avatar.id
    placeholder_id = created.session.avatar_id
    placeholder = await world.db.get(Avatar, placeholder_id)
    previous_placeholder = deepcopy(_avatar_values(placeholder))
    monkeypatch.setattr(
        "backend.engine.manifest_apply.avatar._portrait", AsyncMock(return_value=None)
    )
    ctx = ApplyContext(world.db, created.template.id, {}, world.owner, created.template)
    generated, _ = await persist_avatar(ctx, _manifest_protagonist())
    assert generated.id == response_avatar_id
    world.db.add(
        WorldScene(
            id="ORIGIN", template_id=created.template.id, label="Origin", description="A room."
        )
    )
    await materialize_initial_session_from_template(
        world.db, created.template.id, created.session.id
    )
    await world.db.commit()

    session_avatar = await world.db.get(Avatar, created.session.avatar_id)
    assert session_avatar.id not in {response_avatar_id, placeholder_id}
    assert session_avatar.name == generated.name
    state = await world.db.scalar(
        select(SessionState).where(SessionState.session_id == created.session.id)
    )
    assert state.avatar_id == session_avatar.id
    assert await get_template_avatar(world.db, created.template.id) is generated
    await world.db.refresh(placeholder)
    assert _avatar_values(placeholder) == previous_placeholder


@pytest.mark.parametrize("role", ["user", "assistant", "system"])
async def test_materializer_protects_played_avatar_without_world_rows(avatar_world, role):
    world = avatar_world
    authored = await _add_blueprint(world)
    world.db.add(ChatMessage(session_id="saved-game-1", role=role, content="Synthetic history"))
    await world.db.commit()
    previous = deepcopy(_avatar_values(world.characters[1]))
    await materialize_initial_session_from_template(world.db, world.template.id, "saved-game-1")
    await world.db.commit()
    session = await world.db.get(GameSession, "saved-game-1")
    avatar = await world.db.get(Avatar, session.avatar_id)
    if role == "user":
        assert avatar.id == world.characters[1].id
        assert _avatar_values(avatar) == previous
    else:
        assert avatar.id != world.characters[1].id
        assert avatar.name == authored.name
