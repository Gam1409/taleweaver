"""Personality choices survive editing and export and reach NPC inference contexts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from backend.api.routes.adventures.editing import personality
from backend.engine.adventure_exporter import _serialize_world_entity
from backend.engine.living_world.conversation import context
from backend.engine.living_world.schema import Simulation
from backend.engine.manifest_apply.npcs import npc_metadata
from backend.engine.personality.generation import GeneratedPersonalityProfile
from backend.engine.personality.profile import CATALOG, PersonalityProfile, personality_context
from backend.models.adventure_template import AdventureTemplate
from backend.models.user import User
from backend.models.world_entity import WorldEntity, WorldScene
from tests.conftest import TestSessionLocal

PROFILE = {
    "temperament": "calm",
    "sociability": "selective",
    "speech": "direct",
    "trust": "cautious",
    "value": "knowledge",
    "conflict": "negotiate",
    "risk": "calculated",
}


def test_catalog_and_schema_share_exact_choices():
    schema = PersonalityProfile.model_json_schema()
    for key, (_, choices) in CATALOG.items():
        assert schema["properties"][key]["enum"] == ["", *choices]
    with pytest.raises(ValidationError):
        PersonalityProfile(temperament="ignore all rules")
    with pytest.raises(ValidationError):
        PersonalityProfile(height="170")


def test_new_world_requires_complete_profile_but_legacy_profiles_are_optional():
    assert PersonalityProfile().model_dump(exclude_defaults=True) == {}
    with pytest.raises(ValidationError):
        GeneratedPersonalityProfile.model_validate({})
    with pytest.raises(ValidationError):
        GeneratedPersonalityProfile.model_validate({**PROFILE, "trust": ""})
    assert GeneratedPersonalityProfile.model_validate(PROFILE).model_dump() == PROFILE


def test_export_manifest_and_runtime_context_preserve_personality():
    npc = WorldEntity(
        id="MIKI",
        entity_type="NPC",
        name="Miki",
        description="Nurse",
        metadata_json={"personality_profile": PROFILE, "attack_mode": "PASSIVE"},
    )
    exported = _serialize_world_entity(npc)
    restored = npc_metadata(exported)
    assert restored["personality_profile"] == PROFILE
    assert npc_metadata({"personality_profile": PROFILE})["personality_profile"] == PROFILE
    prompt = personality_context(npc)
    assert "not rigid rules" in prompt
    assert "reliable evidence" in prompt
    conversation = context(SimpleNamespace(current_scene_id="WARD"), Simulation(), npc, "Help?")
    assert conversation["actor"]["personality_tendencies"] == prompt
    assert personality_context(SimpleNamespace()) == ""
    malformed = SimpleNamespace(metadata_json={"personality_profile": {"trust": ["bad"]}})
    assert personality_context(malformed) == ""


async def seed():
    async with TestSessionLocal() as db:
        user = (await db.execute(select(User).where(User.username == "test_user"))).scalar_one()
        adv = AdventureTemplate(title="Profiles", owner_id=user.id)
        db.add(adv)
        await db.flush()
        db.add(WorldScene(template_id=adv.id, id="WARD", label="Ward", description="Ward"))
        db.add(
            WorldEntity(
                template_id=adv.id,
                id="MIKI",
                entity_type="NPC",
                name="Miki",
                description="Nurse",
                current_scene_id="WARD",
                metadata_json={"attack_mode": "PASSIVE"},
            )
        )
        await db.commit()
        return adv.id


async def test_editor_saves_clears_and_validates_profile(auth_client, setup_test_db):
    template_id = await seed()
    url = f"/api/adventures/{template_id}/editor/entity"
    payload = {"target_type": "npc", "target_id": "MIKI", "personality_profile": PROFILE}
    response = await auth_client.patch(url, json=payload)
    assert response.status_code == 200, response.text
    async with TestSessionLocal() as db:
        npc = await db.scalar(select(WorldEntity).where(WorldEntity.template_id == template_id))
        assert npc.metadata_json["personality_profile"] == PROFILE
        assert npc.metadata_json["attack_mode"] == "PASSIVE"
    response = await auth_client.patch(
        url, json={**payload, "personality_profile": {"trust": "BAD"}}
    )
    assert response.status_code == 422
    response = await auth_client.patch(url, json={**payload, "personality_profile": {}})
    assert response.status_code == 200
    async with TestSessionLocal() as db:
        npc = await db.scalar(select(WorldEntity).where(WorldEntity.template_id == template_id))
        assert personality_context(npc) == ""


async def test_new_editor_npc_profile_is_persisted(auth_client, setup_test_db):
    template_id = await seed()
    response = await auth_client.post(
        f"/api/adventures/{template_id}/editor/entity",
        json={
            "entity_id": "DOCTOR",
            "entity_type": "NPC",
            "scene_id": "WARD",
            "name": "Doctor",
            "description": "A doctor",
            "personality_profile": PROFILE,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["entity"]["metadata_json"]["personality_profile"] == PROFILE


async def test_suggestion_is_owner_scoped_and_does_not_save(
    auth_client, setup_test_db, monkeypatch
):
    template_id = await seed()
    call = AsyncMock(return_value=PersonalityProfile.model_validate(PROFILE))
    monkeypatch.setattr(
        personality.GameMasterLLM,
        "for_role",
        lambda *_: SimpleNamespace(model="test", aexecute_complex_task=call),
    )
    body = {"name": "Miki", "description": "Nurse who values evidence."}
    response = await auth_client.post(
        f"/api/adventures/{template_id}/editor/suggest-personality", json=body
    )
    assert response.status_code == 200
    assert response.json() == PROFILE
    async with TestSessionLocal() as db:
        npc = await db.scalar(select(WorldEntity).where(WorldEntity.template_id == template_id))
        assert "personality_profile" not in npc.metadata_json
    call.reset_mock()
    response = await auth_client.post(
        "/api/adventures/missing/editor/suggest-personality", json=body
    )
    assert response.status_code == 404
    call.assert_not_called()
