"""Synthetic authored and saved characters for session portability regressions."""

from copy import deepcopy
from types import SimpleNamespace

import pytest_asyncio
from sqlalchemy import select

from backend.api.routes.adventures.adventure_creation import create_adventure_records
from backend.api.routes.adventures.schemas import CreateAdventureTemplatePayload
from backend.core.adventure_format import CURRENT_VERSION
from backend.models.avatar import Avatar
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.models.world_entity import WorldEntity, WorldScene

REVEAL_RULE = "The hidden token appears when ##CHEST is opened."
UNLOCK_RULE = "Legacy authored opening hint."
PROFILE = {"version": 1, "appearance": {"age_years": 43, "hair": "dark"}, "worn": []}
IDENTITY = {"gender": "nonbinary", "age_years": 43, "visual_profile": PROFILE}
NPC_FACTS = {
    "goal": "Protect the archive.",
    "character": "Patient and precise.",
    "notes": "Keeping watch beside the entrance.",
    "voice": "en-US-Neural2-A",
    "movement_type": "MOVABLE",
    "moveable": True,
    "allowed_scenes": ["ROOM"],
    "is_attackable": False,
    "is_killable": False,
    **IDENTITY,
}


def entity_definitions() -> list[dict]:
    return [
        {
            "id": "GUIDE",
            "entity_type": "NPC",
            "name": "Archive guide",
            "description": "A watchful guide.",
            "current_scene_id": "ROOM",
            "inventory": [],
            "metadata_json": {"personality_profile": {"temperament": "calm", "value": "duty"}},
            **deepcopy(NPC_FACTS),
        },
        {
            "id": "CHEST",
            "entity_type": "OBJECT",
            "item_type": "CONTAINER",
            "name": "Archive chest",
            "description": "A locked wooden chest.",
            "current_scene_id": "ROOM",
            "metadata_json": {"locked": True, "item_to_unlock": "BRASS_KEY"},
        },
        {
            "id": "TOKEN",
            "entity_type": "OBJECT",
            "item_type": "PICKABLE",
            "name": "Hidden token",
            "description": "A small token.",
            "current_scene_id": "ROOM",
            "spatial_position": "inside a concealed compartment",
            "is_hidden": True,
            "reveal_rule": REVEAL_RULE,
            "unlock_rule": UNLOCK_RULE,
            "wearable_slots": ["Neck"],
            "combination_ingredients": ["BRASS_KEY"],
            "is_portable": False,
        },
    ]


@pytest_asyncio.fixture(params=["rpg", "vn"])
async def entity_world(request, auth_client, db_session):
    owner = await db_session.scalar(select(User).where(User.username == "test_user"))
    defaults = {"mode": "shadow", "actor_ids": ["GUIDE"]} if request.param == "vn" else None
    created = await create_adventure_records(
        db_session,
        CreateAdventureTemplatePayload(
            title="Portable character facts",
            avatar_name="Archive keeper",
            skip_generation=True,
            rule_enforcement_mode=request.param,
            npc_personality_settings=defaults,
        ),
        owner,
    )
    template = created.template
    template.origin_id = "ROOM"
    template.sequences = [{"id": "CHAPTER", "title": "Archive", "order": 1}]
    template.original_manifest = {
        **(template.original_manifest or {}),
        "format_version": CURRENT_VERSION,
        "start_scene_id": "ROOM",
        "scenes": [
            {"id": "ROOM", "name": "Archive", "description": "A quiet room."},
            {"id": "OTHER", "name": "Courtyard", "description": "A quiet courtyard."},
        ],
        "protagonist": {"name": "Archive keeper", **deepcopy(IDENTITY)},
        "clothing_settings": {"detailed": False},
    }
    for field, value in IDENTITY.items():
        setattr(created.avatar, field, deepcopy(value))
    created.avatar.exp = 250
    saved = Avatar(user_id=owner.id, name="Saved keeper", template_id=None, **deepcopy(IDENTITY))
    db_session.add(saved)
    await db_session.flush()
    source = GameSession(
        id="portable-source",
        user_id=owner.id,
        avatar_id=saved.id,
        template_id=template.id,
        adventure_title=template.title,
    )
    db_session.add(source)
    await db_session.flush()
    initial = await db_session.scalar(
        select(SessionState).where(SessionState.session_id == created.session.id)
    )
    db_session.add(
        SessionState(
            session_id=source.id,
            user_id=owner.id,
            avatar_id=saved.id,
            template_id=template.id,
            current_scene_id="ROOM",
            entity_states=deepcopy(initial.entity_states),
        )
    )
    for scope in ({"template_id": template.id}, {"session_id": source.id}):
        db_session.add_all(
            WorldScene(id=scene, label=scene, description="A quiet room.", **scope)
            for scene in ("ROOM", "OTHER")
        )
        db_session.add_all(
            WorldEntity(**deepcopy(values), **scope) for values in entity_definitions()
        )
    await db_session.commit()
    return SimpleNamespace(
        db=db_session,
        client=auth_client,
        owner=owner,
        template=template,
        created=created,
        source=source,
        mode=request.param,
    )
