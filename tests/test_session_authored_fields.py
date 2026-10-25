"""Starting, copying and transporting a save must retain authored characterization."""

import io
import json
import zipfile
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from backend.core.config import settings
from backend.models.adventure_template import AdventureTemplate
from backend.models.avatar import Avatar
from backend.models.game_session import GameSession
from backend.models.user import User
from backend.models.world_entity import WorldEntity, WorldScene
from tests.conftest import TestSessionLocal

TEMPLATE = "authored-fields-template"
DECORATIONS = ["Paper cranes", "An unlit brass lantern"]
NPC_FIELDS = ("Find her missing brother.", "Cautious, direct and protective.")
MANIFEST_FIELDS = ("Keep the village safe.", "Curious, patient and observant.")
TEMPLATE_FIELDS = ("Repay an old debt.", "Practical, witty and suspicious.")


async def seed_template(monkeypatch, tmp_path, mode, avatar_source, decorations=DECORATIONS):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        "backend.engine.adventure_updates.check_template_update",
        lambda *_: {"is_legacy_format": False, "can_start": True},
    )
    async with TestSessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == "test_user"))
        template = AdventureTemplate(
            id=TEMPLATE,
            title="An authored story",
            owner_id=user.id,
            is_ready=True,
            rule_enforcement_mode=mode,
            strict_rules=mode == "rpg",
            original_manifest={
                "protagonist": {
                    "name": "Ari",
                    "goal": MANIFEST_FIELDS[0],
                    "character": MANIFEST_FIELDS[1],
                },
                "scenes": [{"id": "HOUSE"}],
            },
        )
        db.add(template)
        db.add(
            WorldScene(
                id="HOUSE",
                template_id=TEMPLATE,
                label="House",
                description="A quiet house.",
                decorative_objects=deepcopy(decorations),
            )
        )
        db.add(
            WorldEntity(
                id="LINA",
                template_id=TEMPLATE,
                entity_type="NPC",
                name="Lina",
                description="A traveler.",
                current_scene_id="HOUSE",
                goal=NPC_FIELDS[0],
                character=NPC_FIELDS[1],
            )
        )
        if avatar_source == "template":
            db.add(
                Avatar(
                    id="authored-avatar",
                    template_id=TEMPLATE,
                    user_id=user.id,
                    name="Ari",
                    goal=TEMPLATE_FIELDS[0],
                    character=TEMPLATE_FIELDS[1],
                )
            )
        await db.commit()


async def read_session_fields(db, session_id):
    session = await db.get(GameSession, session_id)
    avatar = await db.get(Avatar, session.avatar_id)
    npc = await db.scalar(
        select(WorldEntity).where(WorldEntity.session_id == session_id, WorldEntity.id == "LINA")
    )
    scene = await db.scalar(
        select(WorldScene).where(WorldScene.session_id == session_id, WorldScene.id == "HOUSE")
    )
    return avatar, npc, scene


def assert_fields(rows, protagonist_fields, decorations=DECORATIONS):
    avatar, npc, scene = rows
    assert (avatar.goal, avatar.character) == protagonist_fields
    assert (npc.goal, npc.character) == NPC_FIELDS
    assert scene.decorative_objects == decorations


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["rpg", "vn"])
@pytest.mark.parametrize("avatar_source", ["template", "manifest"])
async def test_start_copy_and_ads_roundtrip_preserve_authored_fields(
    auth_client, monkeypatch, tmp_path, mode, avatar_source
):
    await seed_template(monkeypatch, tmp_path, mode, avatar_source)
    started = await auth_client.post(f"/api/adventures/{TEMPLATE}/sessions/start")
    assert started.status_code == 201, started.text
    source_id = started.json()["game_id"]
    expected = TEMPLATE_FIELDS if avatar_source == "template" else MANIFEST_FIELDS
    async with TestSessionLocal() as db:
        assert_fields(await read_session_fields(db, source_id), expected)

    copied = await auth_client.post(f"/api/adventures/sessions/{source_id}/copy")
    assert copied.status_code == 201, copied.text
    copy_id = copied.json()["game_id"]
    exported = await auth_client.get(f"/api/adventures/sessions/{copy_id}/export")
    assert exported.status_code == 200, exported.text
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        manifest = json.loads(archive.read("session.json"))
    assert (manifest["avatar"]["goal"], manifest["avatar"]["character"]) == expected
    assert manifest["world_scenes"][0]["decorative_objects"] == DECORATIONS
    assert manifest["world_entities"][0]["goal"] == NPC_FIELDS[0]
    imported = await auth_client.post(
        "/api/adventures/sessions/import",
        files={"file": ("authored.ads", exported.content, "application/zip")},
    )
    assert imported.status_code == 200, imported.text
    imported_id = imported.json()["game_id"]
    async with TestSessionLocal() as db:
        for session_id in (source_id, copy_id, imported_id):
            assert_fields(await read_session_fields(db, session_id), expected)

    # Editing a live save or the template after copying must not rewrite the copy.
    async with TestSessionLocal() as db:
        avatar, npc, scene = await read_session_fields(db, source_id)
        avatar.goal = "A new personal goal"
        npc.character = "Changed through later events"
        scene.decorative_objects.append("A newly placed chair")
        flag_modified(scene, "decorative_objects")
        template_scene = await db.scalar(
            select(WorldScene).where(
                WorldScene.template_id == TEMPLATE, WorldScene.session_id.is_(None)
            )
        )
        template_scene.decorative_objects.append("A later template edit")
        flag_modified(template_scene, "decorative_objects")
        await db.commit()
    async with TestSessionLocal() as db:
        for session_id in (copy_id, imported_id):
            assert_fields(await read_session_fields(db, session_id), expected)


@pytest.mark.asyncio
@pytest.mark.parametrize("decorations", [None, []])
async def test_empty_authored_fields_remain_empty_without_invented_backfill(
    auth_client, monkeypatch, tmp_path, decorations
):
    await seed_template(monkeypatch, tmp_path, "vn", "template", decorations)
    async with TestSessionLocal() as db:
        avatar = await db.get(Avatar, "authored-avatar")
        avatar.goal, avatar.character = None, ""
        npc = await db.scalar(select(WorldEntity).where(WorldEntity.template_id == TEMPLATE))
        npc.goal, npc.character = "", None
        await db.commit()
    started = await auth_client.post(f"/api/adventures/{TEMPLATE}/sessions/start")
    assert started.status_code == 201, started.text
    copied = await auth_client.post(f"/api/adventures/sessions/{started.json()['game_id']}/copy")
    assert copied.status_code == 201, copied.text
    async with TestSessionLocal() as db:
        for session_id in (started.json()["game_id"], copied.json()["game_id"]):
            avatar, npc, scene = await read_session_fields(db, session_id)
            assert (avatar.goal, avatar.character) == (None, "")
            assert (npc.goal, npc.character) == ("", None)
            assert scene.decorative_objects == decorations


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["rpg", "chat"])
async def test_preserved_authored_npc_fields_stay_private_in_started_and_copied_chat(
    auth_client, monkeypatch, tmp_path, mode
):
    await seed_template(monkeypatch, tmp_path, mode, "template")
    monkeypatch.setattr(
        "backend.api.routes.adventures.gameplay.resolve_prompt_suggestions",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "backend.api.routes.adventures.gameplay.schedule_npc_journal", lambda *_: None
    )
    async with TestSessionLocal() as db:
        npc = await db.scalar(select(WorldEntity).where(WorldEntity.template_id == TEMPLATE))
        npc.hp, npc.max_hp = 37, 45
        await db.commit()
    started = await auth_client.post(f"/api/adventures/{TEMPLATE}/sessions/start")
    assert started.status_code == 201, started.text
    source_id = started.json()["game_id"]
    copied = await auth_client.post(f"/api/adventures/sessions/{source_id}/copy")
    assert copied.status_code == 201, copied.text
    for session_id in (source_id, copied.json()["game_id"]):
        response = await auth_client.get(f"/api/adventures/{session_id}/chat")
        assert response.status_code == 200, response.text
        npc_view = next(entity for entity in response.json()["entities"] if entity["id"] == "LINA")
        assert "goal" not in npc_view and "character" not in npc_view
        assert npc_view["hp"] == 37 and npc_view["max_hp"] == 45
        assert "is_attackable" in npc_view
        for private in NPC_FIELDS:
            assert private not in response.text
        async with TestSessionLocal() as db:
            assert_fields(await read_session_fields(db, session_id), TEMPLATE_FIELDS)
