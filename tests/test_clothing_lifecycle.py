"""Canonical outfits survive generation, copies, exports and session rewind."""

from copy import deepcopy

import pytest_asyncio
from sqlalchemy import select

from backend.core.adventure_format import CURRENT_VERSION
from backend.core.config import settings
from backend.engine.adventure_exporter import AdventureExporter
from backend.engine.adventure_importer import AdventureTemplateImporter
from backend.engine.manifest_apply import avatar as avatar_apply
from backend.engine.manifest_apply import npcs as npc_apply
from backend.engine.session_checkpoint_service import SessionCheckpointService
from backend.engine.world_generator import WorldGenerator
from backend.models.adventure_template import AdventureTemplate
from backend.models.avatar import Avatar
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_clothing_generation import garment, profile


@pytest_asyncio.fixture
async def clothing_world(auth_client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    seen = []

    async def avatar_portrait(ctx, avatar, prot):
        assert avatar.visual_profile["worn"][0]["item_id"] == "COAT"
        assert ctx.manifest["objects"][0]["clothing"] == garment()
        seen.append("avatar")

    async def npc_portrait(ctx, npc, *args):
        assert npc["visual_profile"]["worn"][0]["item_id"] == "DRESS"
        seen.append("npc")

    monkeypatch.setattr(avatar_apply, "_portrait", avatar_portrait)
    monkeypatch.setattr(npc_apply, "_npc_image", npc_portrait)
    manifest = {
        "format_version": CURRENT_VERSION,
        "clothing_settings": {"detailed": False},  # The model cannot undo the author's choice.
        "protagonist": {
            "name": "Hero",
            "role": "Traveller",
            "description": "Brown-haired traveller.",
            "starting_inventory": ["COAT"],
            "starting_equipment": {},
            "visual_profile": profile(),
        },
        "scenes": [{"id": "ROOM", "name": "Room", "description": "A quiet room."}],
        "exits": [],
        "npcs": [
            {
                "id": "LINA",
                "name": "Lina",
                "description": "A woman in an everyday dress.",
                "start_scene_id": "ROOM",
                "inventory": ["DRESS"],
                "visual_profile": profile("DRESS", 31),
            }
        ],
        "objects": [
            {
                "id": "COAT",
                "name": "Coat",
                "description": "Wool travel coat",
                "item_type": "WEARABLE",
                "wearable_slots": ["Chest"],
                "start_scene_id": "ROOM",
                "clothing": garment(),
            },
            {
                "id": "DRESS",
                "name": "Dress",
                "description": "Linen everyday dress",
                "item_type": "WEARABLE",
                "wearable_slots": ["Chest"],
                "start_scene_id": "ROOM",
                "clothing": garment(),
            },
        ],
        "quests": [],
        "awards": [],
        "sequences": [],
    }
    async with TestSessionLocal() as db:
        user = await db.scalar(select(User))
        template = AdventureTemplate(
            id="clothing-world",
            title="Clothing world",
            rule_enforcement_mode="vn",
            owner_id=user.id,
            original_manifest={"clothing_settings": {"detailed": True}},
        )
        db.add(template)
        await db.commit()
        await WorldGenerator.apply_manifest(db, template.id, manifest)
        template.is_ready = True
        await db.commit()
    assert seen == ["avatar", "npc"]
    return manifest


async def actors(db, session_id):
    session = await db.get(GameSession, session_id)
    avatar = await db.get(Avatar, session.avatar_id)
    npc = await db.scalar(
        select(WorldEntity).where(WorldEntity.session_id == session_id, WorldEntity.id == "LINA")
    )
    state = await db.scalar(select(SessionState).where(SessionState.session_id == session_id))
    return avatar, npc, state


async def start(client, template_id="clothing-world"):
    response = await client.post(f"/api/adventures/{template_id}/sessions/start", json={})
    assert response.status_code == 201, response.text
    return response.json()["game_id"]


async def test_initial_profiles_and_canonical_items_exist_before_portraits(
    auth_client, clothing_world
):
    async with TestSessionLocal() as db:
        template = await db.get(AdventureTemplate, "clothing-world")
        avatar = await db.scalar(select(Avatar).where(Avatar.template_id == template.id))
        npc = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.template_id == template.id, WorldEntity.id == "LINA"
            )
        )
        objects = (
            await db.scalars(
                select(WorldEntity).where(
                    WorldEntity.template_id == template.id, WorldEntity.entity_type == "OBJECT"
                )
            )
        ).all()
        assert template.original_manifest["clothing_settings"] == {"detailed": True}
        assert len(objects) == 2
        assert avatar.inventory == ["COAT"]
        assert avatar.visual_profile["worn"][0]["item_id"] == "COAT"
        assert npc.inventory[0]["id"] == "DRESS"
        assert npc.inventory[0]["clothing"] == garment()
        assert npc.visual_profile["appearance"]["age_years"] == 31
        assert all(obj.metadata_json["clothing"] == garment() for obj in objects)


async def test_session_start_copy_ads_and_rewind_preserve_clothing(auth_client, clothing_world):
    sid = await start(auth_client)
    async with TestSessionLocal() as db:
        avatar, npc, state = await actors(db, sid)
        expected_avatar, expected_npc = (
            deepcopy(avatar.visual_profile),
            deepcopy(npc.visual_profile),
        )
        assert avatar.inventory[0]["metadata_json"]["clothing"] == garment()
        assert npc.inventory[0]["clothing"] == garment()
        assert state.entity_states["__manifest_snapshot__"]["original_manifest"][
            "clothing_settings"
        ] == {"detailed": True}
        checkpoint = await SessionCheckpointService.create_checkpoint(db, sid, "manual")
        await db.commit()
        checkpoint_id = checkpoint.id
        avatar.visual_profile = {**avatar.visual_profile, "worn": []}
        state.entity_states = {
            **state.entity_states,
            "LINA": {"visual_profile": {**npc.visual_profile, "worn": []}},
        }
        await db.commit()
        await SessionCheckpointService.restore_checkpoint(db, sid, checkpoint_id)
        await db.commit()
        assert avatar.visual_profile == expected_avatar
        assert (
            "LINA" not in state.entity_states or "visual_profile" not in state.entity_states["LINA"]
        )
    copy = await auth_client.post(f"/api/adventures/sessions/{sid}/copy")
    assert copy.status_code == 201, copy.text
    exported = await auth_client.get(f"/api/adventures/sessions/{sid}/export")
    assert exported.status_code == 200, exported.text
    imported = await auth_client.post(
        "/api/adventures/sessions/import",
        files={"file": ("clothes.ads", exported.content, "application/zip")},
    )
    assert imported.status_code == 200, imported.text
    async with TestSessionLocal() as db:
        for restored_id in (copy.json()["game_id"], imported.json()["game_id"]):
            avatar, npc, state = await actors(db, restored_id)
            assert avatar.visual_profile == expected_avatar
            assert npc.visual_profile == expected_npc
            assert avatar.inventory[0]["metadata_json"]["clothing"] == garment()
            assert npc.inventory[0]["clothing"] == garment()


async def test_adv_export_import_and_template_copy_preserve_profiles(auth_client, clothing_world):
    async with TestSessionLocal() as db:
        manifest = await AdventureExporter.build_full_manifest(db, "clothing-world")
        assert manifest["clothing_settings"] == {"detailed": True}
        assert manifest["protagonist"]["visual_profile"]["worn"][0]["item_id"] == "COAT"
        assert manifest["npcs"][0]["visual_profile"]["worn"][0]["item_id"] == "DRESS"
        assert manifest["objects"][0]["metadata_json"]["clothing"] == garment()
        owner = (await db.get(AdventureTemplate, "clothing-world")).owner_id
        manifest["adventure"]["title"] = "Imported clothing"
        assert await AdventureTemplateImporter.import_adv_manifest(db, manifest, owner_id=owner)
        imported = await db.scalar(
            select(AdventureTemplate).where(AdventureTemplate.title == "Imported clothing")
        )
        imported_id = imported.id
    copied = await auth_client.post("/api/adventures/clothing-world/copy")
    assert copied.status_code == 201, copied.text
    for template_id in (copied.json()["id"], imported_id):
        sid = await start(auth_client, template_id)
        async with TestSessionLocal() as db:
            avatar, npc, _ = await actors(db, sid)
            assert avatar.visual_profile["appearance"]["hair"] == "Brown hair"
            assert npc.visual_profile["worn"][0]["item_id"] == "DRESS"


async def test_old_checkpoint_without_profile_clears_later_tracking(auth_client, clothing_world):
    sid = await start(auth_client)
    async with TestSessionLocal() as db:
        avatar, _, _ = await actors(db, sid)
        checkpoint = await SessionCheckpointService.create_checkpoint(db, sid, "manual")
        old_snapshot = deepcopy(checkpoint.state_snapshot)
        old_snapshot["avatar"].pop("visual_profile", None)
        checkpoint.state_snapshot = old_snapshot
        await db.commit()
        assert avatar.visual_profile is not None
        await SessionCheckpointService.restore_checkpoint(db, sid, checkpoint.id)
        await db.commit()
        assert avatar.visual_profile is None


async def test_checkpoint_keeps_prior_owned_garments_and_unmarked_imported_rows(
    auth_client, clothing_world
):
    sid = await start(auth_client)
    async with TestSessionLocal() as db:
        avatar, _, _ = await actors(db, sid)
        origin = {"kind": "runtime", "session_id": sid, "source_message_id": "prior"}
        # This creation exists in inventory before the checkpoint, without a world row.
        avatar.inventory = [*avatar.inventory, {"id": "prior_garment", "clothing_origin": origin}]
        checkpoint = await SessionCheckpointService.create_checkpoint(db, sid, "manual")
        await db.commit()
        db.add_all(
            [
                WorldEntity(
                    id="prior_garment",
                    session_id=sid,
                    entity_type="OBJECT",
                    description="",
                    current_scene_id="ROOM",
                    name="Prior",
                    metadata_json={"clothing_origin": origin},
                ),
                WorldEntity(
                    id="garment_legitimate",
                    session_id=sid,
                    entity_type="OBJECT",
                    description="",
                    current_scene_id="ROOM",
                    name="Base",
                    metadata_json={},
                ),
                WorldEntity(
                    id="foreign_origin",
                    session_id=sid,
                    entity_type="OBJECT",
                    description="",
                    current_scene_id="ROOM",
                    name="Imported",
                    metadata_json={"clothing_origin": {**origin, "session_id": "source-save"}},
                ),
                WorldEntity(
                    id="later_created",
                    session_id=sid,
                    entity_type="OBJECT",
                    description="",
                    current_scene_id="ROOM",
                    name="Future",
                    metadata_json={"clothing_origin": {**origin, "source_message_id": "later"}},
                ),
            ]
        )
        await db.commit()
        await SessionCheckpointService.restore_checkpoint(db, sid, checkpoint.id)
        await db.commit()
        identifiers = set(
            (await db.scalars(select(WorldEntity.id).where(WorldEntity.session_id == sid))).all()
        )
        assert {"prior_garment", "garment_legitimate", "foreign_origin"} <= identifiers
        assert "later_created" not in identifiers


async def test_legacy_checkpoint_cleanup_requires_removed_creation_source(
    auth_client, clothing_world
):
    from backend.engine.clothing.lifecycle import CHECKPOINT_KEY
    from backend.models.chat import ChatMessage

    sid = await start(auth_client)
    async with TestSessionLocal() as db:
        checkpoint = await SessionCheckpointService.create_checkpoint(db, sid, "manual")
        snapshot = deepcopy(checkpoint.state_snapshot)
        snapshot.pop(CHECKPOINT_KEY)
        checkpoint.state_snapshot = snapshot
        await db.commit()
        db.add(
            ChatMessage(id="after-clothes", session_id=sid, role="user", content="I take a coat.")
        )
        for identifier, source in (
            ("known_future", "after-clothes"),
            ("uncertain_origin", "unavailable-source"),
        ):
            db.add(
                WorldEntity(
                    id=identifier,
                    session_id=sid,
                    entity_type="OBJECT",
                    description="",
                    current_scene_id="ROOM",
                    name=identifier,
                    metadata_json={
                        "clothing_origin": {
                            "kind": "runtime",
                            "session_id": sid,
                            "source_message_id": source,
                        }
                    },
                )
            )
        await db.commit()
        await SessionCheckpointService.restore_checkpoint(db, sid, checkpoint.id)
        await db.commit()
        identifiers = set(
            (await db.scalars(select(WorldEntity.id).where(WorldEntity.session_id == sid))).all()
        )
        assert "known_future" not in identifiers
        assert "uncertain_origin" in identifiers
