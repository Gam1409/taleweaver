"""Legacy profile preparation is fill-only, transactional and template-scoped."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.engine.clothing import editor_conversion as conversion
from backend.models.adventure_template import AdventureTemplate
from backend.models.avatar import Avatar
from backend.models.game_session import GameSession
from backend.models.user import User
from backend.models.world_entity import WorldEntity

GARMENT = {"layer": 2, "coverage": ["torso", "arms"], "description": "Wool coat"}


@pytest.fixture
async def legacy(db_session, auth_client, monkeypatch):
    user = await db_session.scalar(select(User))
    adventure = AdventureTemplate(
        id="clothing-edit",
        title="Legacy",
        owner_id=user.id,
        rule_enforcement_mode="vn",
        original_manifest={"plot": "Keep this plot", "clothing_settings": {"detailed": False}},
    )
    db_session.add(adventure)
    await db_session.flush()
    avatar = Avatar(
        id="template-hero",
        template_id=adventure.id,
        user_id=user.id,
        name="Hero",
        description="Brown hair, wearing a wool coat.",
        inventory=["COAT"],
    )
    coat = WorldEntity(
        id="COAT",
        template_id=adventure.id,
        entity_type="OBJECT",
        name="Coat",
        description="A wool coat",
        current_scene_id="INVENTORY",
        metadata_json={},
    )
    npc = WorldEntity(
        id="MIRA",
        template_id=adventure.id,
        entity_type="NPC",
        name="Mira",
        description="Dark hair.",
        current_scene_id="ROOM",
        inventory=[],
    )
    db_session.add_all([avatar, coat, npc])
    await db_session.commit()
    result = {
        "actors": [
            {
                "actor_id": "protagonist",
                "appearance": {"hair": "brown", "age_years": 99},
                "worn": [{"item_id": "COAT"}],
                "garments": [{"item_id": "COAT", "clothing": GARMENT}],
            },
            {"actor_id": "npc:MIRA", "appearance": {"hair": "dark"}},
        ]
    }
    llm = SimpleNamespace(
        model="small", request_timeout=20, aexecute_complex_task=AsyncMock(return_value=result)
    )
    monkeypatch.setattr(conversion.GameMasterLLM, "for_role", lambda *args: llm)
    return adventure, avatar, coat, npc, llm


async def test_conversion_preserves_items_and_synchronizes_manifest(db_session, legacy):
    adventure, avatar, coat, npc, llm = legacy
    original_inventory = deepcopy(avatar.inventory)
    result = await conversion.apply_editor_clothing(db_session, adventure, True)
    await db_session.commit()
    assert result == {"prepared_profiles": 2}
    assert avatar.inventory == original_inventory
    assert avatar.visual_profile["appearance"]["age_years"] is None
    assert avatar.visual_profile["appearance"]["hair"] == "brown"
    assert coat.metadata_json["clothing"]["description"] == "Wool coat"
    manifest = adventure.original_manifest
    assert manifest["plot"] == "Keep this plot"
    assert manifest["protagonist"]["visual_profile"] == avatar.visual_profile
    assert manifest["npcs"][0]["visual_profile"] == npc.visual_profile
    assert manifest["objects"][0]["clothing"] == coat.metadata_json["clothing"]
    assert manifest["clothing_settings"]["detailed"]
    llm.aexecute_complex_task.assert_awaited_once()


async def test_disable_reenable_is_lossless_and_does_not_call_model_again(db_session, legacy):
    adventure, avatar, coat, _, llm = legacy
    await conversion.apply_editor_clothing(db_session, adventure, True)
    await db_session.commit()
    profile, metadata = deepcopy(avatar.visual_profile), deepcopy(coat.metadata_json)
    await conversion.apply_editor_clothing(db_session, adventure, False)
    await db_session.commit()
    assert adventure.original_manifest["clothing_settings"] == {"detailed": False}
    assert avatar.visual_profile == profile and coat.metadata_json == metadata
    await conversion.apply_editor_clothing(db_session, adventure, True)
    assert avatar.visual_profile == profile
    assert llm.aexecute_complex_task.await_count == 1


@pytest.mark.parametrize(
    "failure", ["unknown_item", "unknown_actor", "omitted_actor", "underwear", "timeout"]
)
async def test_invalid_conversion_never_partially_mutates_template(db_session, legacy, failure):
    adventure, avatar, coat, npc, llm = legacy
    result = deepcopy(llm.aexecute_complex_task.return_value)
    if failure == "unknown_item":
        result["actors"][0]["worn"] = [{"item_id": "INVENTED"}]
    if failure == "unknown_actor":
        result["actors"][1]["actor_id"] = "UNKNOWN"
    if failure == "omitted_actor":
        result["actors"].pop()
    if failure == "underwear":
        result["actors"][0]["garments"][0]["clothing"]["underwear"] = True
    if failure == "timeout":
        llm.aexecute_complex_task.side_effect = TimeoutError()
    llm.aexecute_complex_task.return_value = result
    before = deepcopy(adventure.original_manifest)
    with pytest.raises(conversion.ClothingConversionError):
        await conversion.apply_editor_clothing(db_session, adventure, True)
    assert adventure.original_manifest == before
    assert avatar.visual_profile is None and npc.visual_profile is None
    assert coat.metadata_json == {}


async def test_only_template_rows_are_prepared(db_session, legacy):
    adventure, _, _, _, llm = legacy
    played = Avatar(
        id="played", template_id=adventure.id, user_id=adventure.owner_id, name="Played"
    )
    db_session.add(played)
    await db_session.flush()
    session = GameSession(
        id="played-session",
        template_id=adventure.id,
        user_id=adventure.owner_id,
        avatar_id=played.id,
    )
    db_session.add(session)
    await db_session.flush()
    played_npc = WorldEntity(
        id="PLAYED_NPC",
        template_id=adventure.id,
        session_id=session.id,
        entity_type="NPC",
        name="Played NPC",
        description="Private history",
        current_scene_id="ROOM",
    )
    db_session.add(played_npc)
    await db_session.commit()
    await conversion.apply_editor_clothing(db_session, adventure, True)
    assert played.visual_profile is None and played_npc.visual_profile is None
    prompt = llm.aexecute_complex_task.call_args.args[1]
    assert "Private history" not in prompt and "PLAYED_NPC" not in prompt


async def test_inline_inventory_garment_metadata_survives_without_object_row(db_session, legacy):
    adventure, avatar, coat, _, _ = legacy
    avatar.inventory = [{"id": "COAT", "name": "Coat", "description": "Wool coat"}]
    await db_session.delete(coat)
    await db_session.commit()
    await conversion.apply_editor_clothing(db_session, adventure, True)
    assert avatar.inventory[0]["clothing"]["description"] == "Wool coat"
    assert adventure.original_manifest["protagonist"]["starting_inventory"] == avatar.inventory


async def test_dictionary_inventory_shape_and_private_metadata_are_preserved(db_session, legacy):
    adventure, avatar, _, _, llm = legacy
    avatar.inventory = {"coat": {"id": "COAT", "name": "Coat", "secret": "private-script"}}
    await db_session.commit()
    await conversion.apply_editor_clothing(db_session, adventure, True)
    assert avatar.inventory["coat"]["secret"] == "private-script"
    assert avatar.inventory["coat"]["clothing"]["description"] == "Wool coat"
    assert "private-script" not in llm.aexecute_complex_task.call_args.args[1]
