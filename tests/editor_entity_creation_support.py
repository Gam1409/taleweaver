"""Owned synthetic editor world and lifecycle payloads for creation regressions."""

from types import SimpleNamespace

import pytest_asyncio
from sqlalchemy import select

from backend.core.adventure_format import CURRENT_VERSION
from backend.models.adventure_template import AdventureTemplate
from backend.models.user import User
from backend.models.world_entity import WorldExit, WorldScene
from tests.conftest import TestSessionLocal

ITEM_EVENTS = ("on_pickup", "on_drop", "on_equip", "on_unequip")
NPC_EVENTS = ("on_defeat", "on_protagonist_enters_scene")


def event_fields(kind: str) -> dict[str, str]:
    prefixes = NPC_EVENTS if kind == "NPC" else ITEM_EVENTS
    values = {}
    for prefix in prefixes:
        values[f"{prefix}_script"] = f"tw.vars.set('{prefix}', tw.vars.get('{prefix}', 0) + 1)"
        values[f"{prefix}_text"] = f"{prefix} authored callback."
    return values


def entity_payload(kind: str, identifier: str | None = None) -> dict:
    return {
        "entity_id": identifier or ("GUIDE" if kind == "NPC" else "COAT"),
        "entity_type": kind,
        "scene_id": "HALL",
        "name": "Archive guide" if kind == "NPC" else "Travel coat",
        "description": "An authored guide." if kind == "NPC" else "A wool travel coat.",
        "item_type": "WEARABLE" if kind == "OBJECT" else None,
        "wearable_slots": ["Chest"] if kind == "OBJECT" else None,
        "spatial_position": "  beside the archive door  ",
        "hp": 12 if kind == "NPC" else None,
        "stamina": 0,
        "mana": 0,
        "is_killable": False,
        "metadata_json": {"extension_data": {"enabled": True}},
        **{key: f" \n{value}\n " for key, value in event_fields(kind).items()},
    }


@pytest_asyncio.fixture
async def entity_creation_world(auth_client):
    response = await auth_client.post(
        "/api/adventures/",
        json={
            "title": "Editor lifecycle callbacks",
            "avatar_name": "Keeper",
            "skip_generation": True,
        },
    )
    assert response.status_code == 201, response.text
    identifiers = response.json()
    async with TestSessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == "test_user"))
        adventure = await db.get(AdventureTemplate, identifiers["adventure_id"])
        adventure.sequences = [{"id": "CHAPTER", "title": "Archive", "order": 1}]
        adventure.original_manifest = {
            **(adventure.original_manifest or {}),
            "format_version": CURRENT_VERSION,
            "start_scene_id": "YARD",
            "scenes": [
                {"id": "YARD", "name": "Courtyard", "description": "An open courtyard."},
                {"id": "HALL", "name": "Archive", "description": "A quiet hall."},
            ],
        }
        db.add_all(
            WorldScene(
                id=identifier, template_id=adventure.id, label=identifier, description="A room."
            )
            for identifier in ("HALL", "YARD")
        )
        db.add(
            WorldExit(
                template_id=adventure.id,
                from_scene_id="YARD",
                to_scene_id="HALL",
                label="Archive door",
            )
        )
        await db.commit()
        return SimpleNamespace(
            client=auth_client, template_id=adventure.id, user_id=user.id, ids=identifiers
        )
