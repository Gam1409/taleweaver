"""Confirmed VN possession changes survive the real applier without clones or lost ownership."""

from copy import deepcopy

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.api.routes.adventures.turn_helpers import TurnProgressionBuilder
from backend.engine.visual_novel.continuity import prepare_intent
from backend.models.adventure_template import AdventureTemplate
from backend.models.avatar import Avatar
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.models.world_entity import WorldEntity

TOKEN = {
    "id": "TOKEN",
    "name": "Family tonic",
    "description": "A keepsake vial",
    "item_type": "CONSUMABLE",
    "image_url": "/data/tonic.png",
    "hp_change": 7,
    "stat_modifier_wisdom": 2,
    "provenance": "From a friend",
}


async def _seed(db, source, world_row):
    user = User(username="vn-owner", hashed_password="pw")
    db.add(user)
    await db.flush()
    adventure = AdventureTemplate(
        id="vn-owner-story",
        owner_id=user.id,
        title="Reunion",
        rule_enforcement_mode="vn",
        strict_rules=False,
    )
    db.add(adventure)
    avatar = Avatar(
        id="owner-avatar",
        user_id=user.id,
        template_id=adventure.id,
        name="Alex",
        role="Visitor",
        inventory=[deepcopy(TOKEN)] if source == "player" else [],
        equipment={"MainHand": deepcopy(TOKEN)} if source == "player" else {},
    )
    db.add(avatar)
    await db.flush()
    db.add(
        GameSession(
            id="owner-session", user_id=user.id, template_id=adventure.id, avatar_id=avatar.id
        )
    )
    await db.flush()
    state = SessionState(
        session_id="owner-session",
        user_id=user.id,
        template_id=adventure.id,
        avatar_id=avatar.id,
        current_scene_id="START",
        entity_states={},
    )
    db.add(state)
    npc = WorldEntity(
        id="NPC",
        session_id=state.session_id,
        entity_type="NPC",
        name="Lena",
        description="A friend",
        current_scene_id="START",
        inventory=[{"id": "NOTE", "name": "Private note"}]
        + ([deepcopy(TOKEN)] if source == "NPC" else []),
    )
    box = WorldEntity(
        id="BOX",
        session_id=state.session_id,
        entity_type="OBJECT",
        name="Box",
        description="An open box",
        item_type="CONTAINER",
        current_scene_id="START",
        is_portable=False,
        inventory=[{"id": "LETTER", "name": "Old letter"}]
        + ([deepcopy(TOKEN)] if source == "BOX" else []),
    )
    db.add_all([npc, box])
    if world_row:
        db.add(
            WorldEntity(
                id="TOKEN",
                session_id=state.session_id,
                entity_type="OBJECT",
                name=TOKEN["name"],
                description=TOKEN["description"],
                current_scene_id="START",
                item_type="CONSUMABLE",
                is_in_inventory=source != "scene",
                image_url=TOKEN["image_url"],
                stat_modifier_wisdom=2,
                metadata_json={"hp_change": 7, "provenance": TOKEN["provenance"]},
            )
        )
    await db.commit()
    manager = GameTurnManager(db, state.session_id, user)
    await manager.initialize()
    return manager


def _proposal(target):
    item = {"id": "TOKEN", "name": "Fabricated label"}
    if target == "player":
        return {"new_inventory_items": [item]}
    if target == "scene":
        return {"spawned_items": [item]}
    return {"updated_entities": [{"entity_id": target, "inventory": [item]}]}


def _inventory(holder, states):
    return states.get(holder.id, {}).get("inventory", holder.inventory or [])


async def _assert_owner(db, manager, target):
    entities = list(
        (await db.execute(select(WorldEntity).where(WorldEntity.session_id == manager.game_id)))
        .scalars()
        .all()
    )
    states = manager.state.entity_states
    owners = []
    carried = next(
        (item for item in manager.avatar.inventory or [] if item.get("id") == "TOKEN"), None
    )
    if carried:
        owners.append("player")
    for holder in entities:
        item = next(
            (item for item in _inventory(holder, states) if item.get("id") == "TOKEN"), None
        )
        if item:
            owners.append(holder.id)
            carried = item
    tokens = [entity for entity in entities if entity.id == "TOKEN"]
    assert len(tokens) <= 1
    if tokens:
        token = tokens[0]
        override = states.get("TOKEN", {})
        if not override.get("is_in_inventory", token.is_in_inventory) and not override.get(
            "is_hidden", token.is_hidden
        ):
            owners.append("scene")
        assert token.image_url == TOKEN["image_url"]
        assert token.stat_modifier_wisdom == 2
    assert owners == [target]
    if target != "scene":
        assert carried["name"] == TOKEN["name"]
        assert carried["image_url"] == TOKEN["image_url"]
        assert carried["stat_modifier_wisdom"] == 2
        assert carried["hp_change"] == 7
        assert carried["provenance"] == TOKEN["provenance"]
    assert not any("_COPY_" in entity.id for entity in entities)
    assert [
        item["id"]
        for item in _inventory(next(e for e in entities if e.id == "NPC"), states)
        if item["id"] != "TOKEN"
    ] == ["NOTE"]
    assert [
        item["id"]
        for item in _inventory(next(e for e in entities if e.id == "BOX"), states)
        if item["id"] != "TOKEN"
    ] == ["LETTER"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source", "target", "world_row"),
    [
        ("scene", "NPC", True),
        ("NPC", "scene", True),
        ("player", "NPC", True),
        ("BOX", "player", True),
        ("BOX", "NPC", True),
        ("NPC", "BOX", True),
        ("scene", "player", True),
        ("NPC", "scene", False),
        ("player", "scene", False),
    ],
)
async def test_confirmed_transfer_has_one_owner_and_preserves_attributes(
    setup_test_db, source, target, world_row
):
    from tests.conftest import TestSessionLocal

    async with TestSessionLocal() as db:
        manager = await _seed(db, source, world_row)
        entities = list(
            (await db.execute(select(WorldEntity).where(WorldEntity.session_id == manager.game_id)))
            .scalars()
            .all()
        )
        event = TurnProgressionBuilder.build_progression_event(
            prepare_intent(manager, _proposal(target), entities)
        )
        await manager._apply_game_event(event)
        await db.commit()
        await db.refresh(manager.state)
        await db.refresh(manager.avatar)
        await _assert_owner(db, manager, target)
        if source == "player":
            assert manager.avatar.equipment.get("MainHand") is None
        if target == "scene":
            entities = list(
                (
                    await db.execute(
                        select(WorldEntity).where(WorldEntity.session_id == manager.game_id)
                    )
                )
                .scalars()
                .all()
            )
            event = TurnProgressionBuilder.build_progression_event(
                prepare_intent(manager, _proposal("player"), entities)
            )
            await manager._apply_game_event(event)
            await db.commit()
            await _assert_owner(db, manager, "player")
