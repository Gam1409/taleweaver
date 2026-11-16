"""Discovery rules and character facts must survive real session boundaries."""

from copy import deepcopy
from hashlib import sha256

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.api.routes.adventures.session_copy_world import clone_saved_world
from backend.api.routes.adventures.session_materializer import (
    _copy_entity,
    materialize_initial_session_from_template,
)
from backend.api.routes.adventures.session_start_world import clone_template_world
from backend.engine.character_identity import identity_facts
from backend.engine.chpm.context import actor_context
from backend.engine.chpm.state import load
from backend.engine.clothing.presentation import player_clothing
from backend.engine.location_context import build_hidden_entities_context
from backend.engine.rule_engine import EntityMovement, GameEvent, WorldEntityUpdate
from backend.engine.session_exporter import SessionExporter
from backend.engine.session_importer import SessionImporter
from backend.models.avatar import Avatar
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity
from tests.session_entity_support import (
    IDENTITY,
    NPC_FACTS,
    REVEAL_RULE,
    UNLOCK_RULE,
    entity_world,
)

__all__ = ["entity_world"]
pytestmark = pytest.mark.asyncio


async def _cross_boundary(world, operation):
    if operation == "materialize":
        await materialize_initial_session_from_template(
            world.db, world.template.id, world.created.session.id
        )
        await world.db.commit()
        return world.created.session.id
    if operation == "import":
        archive = await SessionExporter.export_ads(world.db, world.source.id)
        identifier = await SessionImporter.import_ads(world.db, archive, world.owner.id)
        assert identifier is not None
        return identifier
    path = (
        f"/api/adventures/{world.template.id}/sessions/start"
        if operation == "start"
        else f"/api/adventures/sessions/{world.source.id}/copy"
    )
    response = await world.client.post(path)
    assert response.status_code == 201, response.text
    return response.json()["game_id"]


async def _actors(world, session_id):
    game = await world.db.get(GameSession, session_id, populate_existing=True)
    avatar = await world.db.get(Avatar, game.avatar_id, populate_existing=True)
    entities = list(
        await world.db.scalars(
            select(WorldEntity)
            .where(WorldEntity.session_id == session_id)
            .execution_options(populate_existing=True)
        )
    )
    state = await world.db.scalar(
        select(SessionState)
        .where(SessionState.session_id == session_id)
        .execution_options(populate_existing=True)
    )
    return avatar, {entity.id: entity for entity in entities}, state


@pytest.mark.parametrize("operation", ["start", "materialize", "copy", "import"])
async def test_session_boundary_preserves_discovery_rules_and_character_facts(
    entity_world, operation
):
    world = entity_world
    session_id = await _cross_boundary(world, operation)
    avatar, entities, state = await _actors(world, session_id)
    token, npc = entities["TOKEN"], entities["GUIDE"]

    assert token.reveal_rule == REVEAL_RULE
    assert token.unlock_rule == UNLOCK_RULE
    assert REVEAL_RULE in build_hidden_entities_context([token])
    assert token.is_hidden is True and token.is_portable is False
    assert token.template_id is None and npc.template_id is None
    for field, expected in NPC_FACTS.items():
        assert getattr(npc, field) == expected, field
    assert identity_facts(avatar) == {"gender": "nonbinary", "age_years": 43}
    assert avatar.visual_profile == IDENTITY["visual_profile"]
    assert player_clothing(avatar, world.template.original_manifest)["appearance"]["hair"] == "dark"
    if world.mode == "vn":
        assert load(state).settings.mode == "shadow"
    manager = GameTurnManager(world.db, session_id, world.owner)
    manager.avatar, manager.state, manager.adventure = avatar, state, world.template
    own_facts = await actor_context(manager, npc, None)
    assert own_facts["authored_goal"] == NPC_FACTS["goal"]
    assert own_facts["authored_character"] == NPC_FACTS["character"]
    assert manager.combat._is_npc_attackable(npc) is False
    assert manager.combat._is_npc_killable(npc) is False


@pytest.mark.parametrize("operation", ["start", "materialize", "copy"])
async def test_copied_rules_still_reveal_parent_contents_and_limit_npc_movement(
    entity_world, operation
):
    world = entity_world
    session_id = await _cross_boundary(world, operation)
    avatar, _, state = await _actors(world, session_id)
    manager = GameTurnManager(world.db, session_id, world.owner)
    manager.avatar, manager.state, manager.adventure = avatar, state, world.template
    event = GameEvent(updated_entities=[WorldEntityUpdate(entity_id="CHEST", notes="Opened")])
    await manager.guardrails._enforce_hidden_entity_reveal(event, "")
    assert any(
        update.entity_id == "TOKEN" and update.is_hidden is False
        for update in event.updated_entities
    )
    movement = GameEvent(moved_entities=[EntityMovement(entity_id="GUIDE", to_scene_id="OTHER")])
    violations = await manager.guardrails._enforce_npc_movement_guardrails(movement)
    assert violations and movement.moved_entities == []
    blocked = await world.client.post(
        f"/api/adventures/{session_id}/containers/CHEST/unlock-item",
        json={"item_id": "BRASS_KEY"},
    )
    assert blocked.status_code == 403, blocked.text


@pytest.mark.parametrize("operation", ["start", "materialize", "copy"])
async def test_mutating_copied_entity_json_keeps_source_authoring_independent(
    entity_world, operation
):
    world = entity_world
    target = world.created.session
    avatar = await world.db.get(Avatar, target.avatar_id)
    source_scope = (
        WorldEntity.session_id == world.source.id
        if operation == "copy"
        else WorldEntity.template_id == world.template.id
    )
    source = await world.db.scalar(
        select(WorldEntity).where(source_scope, WorldEntity.id == "TOKEN")
    )
    if operation == "start":
        await clone_template_world(world.db, world.template.id, target, avatar, {}, {})
    elif operation == "materialize":
        world.db.add(_copy_entity(source, target.id, None))
    else:
        await clone_saved_world(world.db, world.source, target, {}, {})
    copied = next(row for row in world.db.new if isinstance(row, WorldEntity) and row.id == "TOKEN")
    await world.db.flush()
    previous = deepcopy((source.wearable_slots, source.combination_ingredients))
    copied.wearable_slots.append("Head")
    copied.combination_ingredients.append("OTHER_ITEM")
    assert (source.wearable_slots, source.combination_ingredients) == previous


async def test_initial_materialization_deeply_copies_identity_and_scene_constraints(entity_world):
    world = entity_world
    source_npc = await world.db.scalar(
        select(WorldEntity).where(
            WorldEntity.template_id == world.template.id, WorldEntity.id == "GUIDE"
        )
    )
    await materialize_initial_session_from_template(
        world.db, world.template.id, world.created.session.id
    )
    await world.db.flush()
    avatar, entities, _ = await _actors(world, world.created.session.id)
    assert avatar.exp == 250
    avatar.visual_profile["appearance"]["hair"] = "changed in play"
    entities["GUIDE"].visual_profile["appearance"]["hair"] = "changed in play"
    entities["GUIDE"].allowed_scenes.append("OTHER")
    assert world.created.avatar.visual_profile == IDENTITY["visual_profile"]
    assert source_npc.visual_profile == IDENTITY["visual_profile"]
    assert source_npc.allowed_scenes == ["ROOM"]


@pytest.mark.parametrize("operation", ["start", "materialize", "copy", "import"])
async def test_legacy_absent_optional_facts_keep_defaults(entity_world, operation):
    world = entity_world
    for row in await world.db.scalars(select(WorldEntity)):
        row.reveal_rule = row.unlock_rule = None
        row.visual_profile = row.gender = row.age_years = row.voice = None
        row.moveable, row.movement_type, row.allowed_scenes = False, "STATIONARY", []
        row.is_attackable = row.is_killable = True
    for row in await world.db.scalars(select(Avatar)):
        row.visual_profile = row.gender = row.age_years = None
    await world.db.commit()
    session_id = await _cross_boundary(world, operation)
    avatar, entities, _ = await _actors(world, session_id)
    npc, token = entities["GUIDE"], entities["TOKEN"]
    assert avatar.gender is avatar.age_years is avatar.visual_profile is None
    assert npc.gender is npc.age_years is npc.visual_profile is npc.voice is None
    assert npc.moveable is False and npc.allowed_scenes == []
    assert npc.is_attackable is True and npc.is_killable is True
    assert token.reveal_rule is token.unlock_rule is None


async def test_saved_copy_retains_clothing_evidence_remapping(entity_world):
    world = entity_world
    text = "The keeper puts on the travel coat."
    world.db.add(
        ChatMessage(id="wear-evidence", session_id=world.source.id, role="assistant", content=text)
    )
    profile = deepcopy(IDENTITY["visual_profile"])
    profile["worn"] = [
        {
            "item_id": "COAT",
            "source": {
                "source_message_id": "wear-evidence",
                "request_id": "wear-evidence",
                "content_hash": sha256(text.encode()).hexdigest(),
                "evidence": text,
            },
        }
    ]
    source_avatar, source_entities, _ = await _actors(world, world.source.id)
    source_npc = source_entities["GUIDE"]
    source_avatar.visual_profile = deepcopy(profile)
    source_npc.visual_profile = deepcopy(profile)
    await world.db.commit()

    copied_id = await _cross_boundary(world, "copy")
    avatar, entities, _ = await _actors(world, copied_id)
    evidence_ids = set(
        await world.db.scalars(select(ChatMessage.id).where(ChatMessage.session_id == copied_id))
    )
    for actor in (avatar, entities["GUIDE"]):
        evidence = actor.visual_profile["worn"][0]["source"]
        assert evidence["source_message_id"] in evidence_ids
        assert evidence["request_id"] == evidence["source_message_id"]
        assert evidence["source_message_id"] != "wear-evidence"
        assert evidence["evidence"] == text
    assert source_avatar.visual_profile == source_npc.visual_profile == profile


async def test_materializer_profile_mutation_does_not_alias_authored_npc(entity_world):
    world = entity_world
    source = await world.db.scalar(
        select(WorldEntity).where(
            WorldEntity.template_id == world.template.id, WorldEntity.id == "GUIDE"
        )
    )
    copied = _copy_entity(source, world.created.session.id, None)
    copied.visual_profile["appearance"]["hair"] = "changed in play"
    copied.allowed_scenes.append("OTHER")
    assert source.visual_profile == IDENTITY["visual_profile"]
    assert source.allowed_scenes == ["ROOM"]


async def test_materializer_retry_preserves_session_npc_changes(entity_world):
    world = entity_world
    await materialize_initial_session_from_template(
        world.db, world.template.id, world.created.session.id
    )
    await world.db.commit()
    _, entities, _ = await _actors(world, world.created.session.id)
    npc = entities["GUIDE"]
    previous_pk = npc.pk
    npc.goal = "A goal changed during play."
    npc.allowed_scenes = ["OTHER"]
    npc.is_attackable = True
    await world.db.commit()
    await materialize_initial_session_from_template(
        world.db, world.template.id, world.created.session.id
    )
    await world.db.commit()
    _, entities, _ = await _actors(world, world.created.session.id)
    npc = entities["GUIDE"]
    assert npc.pk == previous_pk
    assert npc.goal == "A goal changed during play."
    assert npc.allowed_scenes == ["OTHER"] and npc.is_attackable is True
