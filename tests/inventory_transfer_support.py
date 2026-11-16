"""Owned synthetic worlds for inventory transfer and crafting regressions."""

from copy import deepcopy

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.models.adventure_template import AdventureTemplate
from backend.models.avatar import Avatar
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.models.world_entity import WorldEntity, WorldScene

POTION = {
    "id": "POTION",
    "name": "Archive tonic",
    "description": "A sealed herbal tonic.",
    "item_type": "CONSUMABLE",
    "image_url": "/data/fixture-tonic.png",
    "hp_change": 7,
    "provenance": {"source_item_id": "POTION", "batch": "archive"},
    "condition_links": [{"condition_id": "ARCHIVE_LOCK", "item_id": "POTION"}],
}


async def seed_manager(db, *, mode="rpg", inventory=None):
    user = User(username="transfer-player", hashed_password="fixture")
    db.add(user)
    await db.flush()
    adventure = AdventureTemplate(
        id="transfer-template",
        owner_id=user.id,
        title="Archive workshop",
        rule_enforcement_mode=mode,
        strict_rules=mode == "rpg",
        sequences=[],
    )
    db.add(adventure)
    await db.flush()
    avatar = Avatar(
        id="transfer-avatar",
        user_id=user.id,
        name="Keeper",
        role="Visitor",
        hp=100,
        inventory=deepcopy(inventory or []),
        equipment={},
    )
    db.add(avatar)
    await db.flush()
    db.add(
        GameSession(
            id="transfer-session", user_id=user.id, template_id=adventure.id, avatar_id=avatar.id
        )
    )
    await db.flush()
    state = SessionState(
        session_id="transfer-session",
        user_id=user.id,
        template_id=adventure.id,
        avatar_id=avatar.id,
        current_scene_id="START",
        entity_states={},
    )
    db.add(state)
    db.add(
        WorldScene(
            id="START",
            session_id=state.session_id,
            label="Workshop",
            description="An archive workshop.",
        )
    )
    await db.commit()
    manager = GameTurnManager(db, state.session_id, user)
    assert await manager.initialize()
    return manager


def potion_row(manager, *, template=False):
    return WorldEntity(
        id=POTION["id"],
        template_id=manager.adventure.id if template else None,
        session_id=None if template else manager.game_id,
        entity_type="OBJECT",
        item_type="CONSUMABLE",
        name=POTION["name"],
        description=POTION["description"],
        current_scene_id="START",
        is_hidden=False,
        is_in_inventory=False,
        image_url=POTION["image_url"],
        metadata_json=deepcopy(POTION),
    )
