"""New authoring fields participate in validation, fix context and persisted repairs."""

from copy import deepcopy

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from backend.api.routes.adventures.editing.ai_fix_context import (
    _format_focused_world_block,
    _summarize_world_for_fix,
)
from backend.api.routes.adventures.editing.ai_fix_patches import _apply_proposal_patch
from backend.core.world_validator import validate_adventure
from backend.engine.adventure_exporter import AdventureExporter
from backend.engine.authoring_completion import complete_character
from backend.engine.clothing.profiles import garment_for_item
from backend.engine.personality.profile import CATALOG
from backend.models.adventure_template import AdventureTemplate
from backend.models.avatar import Avatar
from backend.models.world_entity import WorldEntity
from backend.schemas.validation import FixProposalEntityPatch
from tests.conftest import TestSessionLocal
from tests.test_editor_entity_update import _seed

TRAITS = {key: next(iter(values[1])) for key, values in CATALOG.items()}
OUTFIT = {
    "name": "Travel coat",
    "description": "A gray wool travel coat.",
    "wearable_slots": ["Chest"],
    "clothing": {
        "layer": 2,
        "coverage": ["torso", "arms"],
        "opaque": True,
        "underwear": False,
        "description": "Gray wool.",
    },
}


def test_completeness_groups_character_gaps_and_checks_wearables():
    npc = {
        "id": "NPC",
        "name": "Guard",
        "entity_type": "NPC",
        "current_scene_id": "HALL",
        "description": "A guard.",
    }
    item = {
        "id": "COAT",
        "entity_type": "OBJECT",
        "item_type": "WEARABLE",
        "current_scene_id": "HALL",
    }
    findings = validate_adventure(
        {
            "adventure": {},
            "scenes": [{"id": "HALL", "description": ""}],
            "entities_all": [npc, item],
        }
    )
    gaps = [f for f in findings if f.code == "character_details_incomplete"]
    assert len(gaps) == 1
    assert "personality_profile.temperament" in gaps[0].context["missing_fields"]
    assert any(f.code == "scene_description_missing" for f in findings)
    assert any(f.code == "wearable_details_incomplete" for f in findings)


def test_intentional_outfit_exemption_and_unknown_age_are_not_forced():
    animal = {
        "id": "CAT",
        "name": "Cat",
        "entity_type": "NPC",
        "description": "A cat.",
        "goal": "Rest",
        "character": "Quiet",
        "metadata_json": {
            "personality_profile": TRAITS,
            "outfit_exemption": "Animal with natural fur.",
        },
    }
    findings = validate_adventure({"adventure": {}, "entities_all": [animal]})
    assert not any(f.code == "character_details_incomplete" for f in findings)


def test_fix_context_contains_protagonist_traits_clothing_and_owned_items():
    source = {
        "adventure": {},
        "protagonist": {"id": "hero", "name": "Hero", "age_years": 28, "inventory": ["COAT"]},
        "npcs": [],
        "objects": [
            {
                "id": "COAT",
                "name": "Coat",
                "clothing": OUTFIT["clothing"],
                "wearable_slots": ["Chest"],
            }
        ],
    }
    summary = _summarize_world_for_fix(source)
    context = _format_focused_world_block(summary, location="protagonist:player")
    assert "TARGET PROTAGONIST" in context
    assert '"age_years": 28' in context
    assert '"coverage": ["torso", "arms"]' in context
    assert '"wearable_slots": ["Chest"]' in context


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["npc", "protagonist"])
async def test_outfit_completion_is_owned_preserves_facts_and_is_idempotent(
    auth_client, setup_test_db, kind
):
    template_id = await _seed()
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, template_id)
        model = Avatar if kind == "protagonist" else WorldEntity
        actor = await db.scalar(select(model).where(model.template_id == template_id))
        actor.age_years = 17
        if kind == "npc":
            actor.metadata_json = {"personality_profile": {"temperament": "energetic"}}
        else:
            actor.equipment = {"Chest": {"id": "OLD", "name": "Existing equipment"}}
        fields = {
            "age_years": 30,
            "personality_profile": TRAITS,
            "appearance": {"hair": "black", "features": "A faint scar", "age_years": 45},
            "outfit": [deepcopy(OUTFIT)],
        }
        patch = FixProposalEntityPatch(
            target_type=kind,
            target_id=actor.id,
            description="Complete ordinary outfit",
            field_updates=fields,
        )
        await _apply_proposal_patch(db=db, template_id=template_id, adv=adventure, patch=patch)
        await db.flush()
        await _apply_proposal_patch(db=db, template_id=template_id, adv=adventure, patch=patch)
        await db.commit()
        await db.refresh(actor)
        clothes = list(
            await db.scalars(
                select(WorldEntity).where(
                    WorldEntity.template_id == template_id, WorldEntity.item_type == "WEARABLE"
                )
            )
        )
        assert len(clothes) == 1
        assert len(actor.visual_profile["worn"]) == 1
        assert actor.visual_profile["worn"][0]["item_id"] == clothes[0].id
        assert actor.inventory[0]["id"] == clothes[0].id
        assert actor.age_years == actor.visual_profile["appearance"]["age_years"] == 17
        assert clothes[0].session_id is None and clothes[0].is_in_inventory
        if kind == "npc":
            assert actor.metadata_json["personality_profile"]["temperament"] == "energetic"
            assert all(actor.metadata_json["personality_profile"][key] for key in CATALOG)
        else:
            assert actor.equipment["Chest"]["id"] == "OLD"
        manifest = adventure.original_manifest
        assert len(manifest["objects"]) == 1
        assert manifest["objects"][0]["id"] == clothes[0].id
        exported = await AdventureExporter.build_full_manifest(db, template_id)
        exported_clothes = [item for item in exported["objects"] if item["id"] == clothes[0].id]
        assert len(exported_clothes) == 1
        exported_garment = garment_for_item(exported_clothes[0])
        assert exported_garment is not None and exported_garment.layer == 2
        exported_actor = exported["protagonist"] if kind == "protagonist" else exported["npcs"][0]
        assert exported_actor["visual_profile"]["worn"][0]["item_id"] == clothes[0].id


@pytest.mark.asyncio
async def test_completion_rejects_foreign_possessions_and_invalid_traits(
    auth_client, setup_test_db
):
    template_id = await _seed()
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, template_id)
        actor = await db.scalar(select(Avatar).where(Avatar.template_id == template_id))
        other = WorldEntity(
            id="FOREIGN",
            template_id=template_id,
            entity_type="OBJECT",
            name="Other coat",
            description="Other",
            current_scene_id="HALL",
            item_type="WEARABLE",
            metadata_json={"clothing": OUTFIT["clothing"]},
        )
        db.add(other)
        await db.flush()
        with pytest.raises(HTTPException, match="belong"):
            await complete_character(
                db,
                adventure,
                actor,
                {
                    "appearance": {"features": "Traveler"},
                    "outfit": [{**OUTFIT, "item_id": "FOREIGN"}],
                },
            )
        with pytest.raises(HTTPException, match="Invalid structured"):
            await complete_character(
                db, adventure, actor, {"personality_profile": {"temperament": "invented"}}
            )
        assert actor.visual_profile is None


@pytest.mark.asyncio
async def test_wearable_patch_persists_slots_and_metadata(auth_client, setup_test_db):
    template_id = await _seed()
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, template_id)
        coat = WorldEntity(
            id="COAT",
            template_id=template_id,
            entity_type="OBJECT",
            name="Coat",
            description="Wool",
            current_scene_id="HALL",
            item_type="WEARABLE",
        )
        db.add(coat)
        await db.flush()
        patch = FixProposalEntityPatch(
            target_type="object",
            target_id="COAT",
            description="Complete metadata",
            field_updates={"wearable_slots": ["Chest"], "clothing": OUTFIT["clothing"]},
        )
        await _apply_proposal_patch(db=db, template_id=template_id, adv=adventure, patch=patch)
        await db.commit()
        await db.refresh(coat)
        assert coat.wearable_slots == ["Chest"]
        assert coat.metadata_json["clothing"]["layer"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "age,mature,detailed,allowed",
    [
        (25, True, True, True),
        (17, True, True, False),
        (None, True, True, False),
        (25, False, True, False),
        (25, True, False, False),
    ],
)
async def test_inner_layers_require_preferences_and_preexisting_adult_age(
    auth_client, setup_test_db, age, mature, detailed, allowed
):
    template_id = await _seed()
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, template_id)
        adventure.original_manifest = {
            "nsfw_settings": {"enabled": mature},
            "clothing_settings": {"detailed": detailed},
        }
        actor = await db.scalar(select(Avatar).where(Avatar.template_id == template_id))
        actor.age_years = age
        inner = deepcopy(OUTFIT)
        inner.update(name="Cotton undergarment", wearable_slots=["Legs"])
        inner["clothing"].update(layer=0, coverage=["pelvis"], underwear=True)
        proposal = {"age_years": 30, "appearance": {"features": "Traveler"}, "outfit": [inner]}
        if not allowed:
            with pytest.raises(HTTPException, match="already established adult"):
                await complete_character(db, adventure, actor, proposal)
            return
        await complete_character(db, adventure, actor, proposal)
        await db.commit()
        assert actor.inventory[0]["clothing"]["underwear"] is True
        assert actor.visual_profile["worn"][0]["item_id"] == actor.inventory[0]["id"]


def test_mature_validation_reviews_missing_inner_layers_only_for_adults():
    npc = {
        "id": "NPC",
        "name": "Guard",
        "entity_type": "NPC",
        "description": "Guard",
        "goal": "Guard",
        "character": "Calm",
        "age_years": 25,
        "metadata_json": {"personality_profile": TRAITS},
        "visual_profile": {"appearance": {"features": "A guard"}, "worn": [{"item_id": "COAT"}]},
    }
    item = {
        "id": "COAT",
        "entity_type": "OBJECT",
        "item_type": "WEARABLE",
        "wearable_slots": ["Chest"],
        "clothing": OUTFIT["clothing"],
    }
    payload = {
        "adventure": {
            "original_manifest": {
                "nsfw_settings": {"enabled": True},
                "clothing_settings": {"detailed": True},
            }
        },
        "entities_all": [npc, item],
    }
    findings = validate_adventure(payload)
    assert any(
        "outfit.inner_layers_review" in (f.context or {}).get("missing_fields", [])
        for f in findings
    )
    npc["age_years"] = 17
    assert not any(
        "outfit.inner_layers_review" in (f.context or {}).get("missing_fields", [])
        for f in validate_adventure(payload)
    )


@pytest.mark.asyncio
async def test_partial_completion_keeps_unresolved_finding_visible(auth_client, setup_test_db):
    from datetime import datetime, timezone

    from backend.models.validation_run import ValidationRun

    template_id = await _seed()
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, template_id)
        db.add(
            ValidationRun(
                template_id=template_id,
                user_id=adventure.owner_id,
                run_at=datetime.now(timezone.utc),
                structural_findings=[
                    {
                        "severity": "warn",
                        "code": "character_details_incomplete",
                        "location": "npc:GUARD",
                        "message": "Incomplete",
                    }
                ],
                ai_findings=[],
            )
        )
        await db.commit()
    response = await auth_client.post(
        f"/api/adventures/{template_id}/editor/validate/findings/apply-fix",
        json={
            "finding_signature": "warn|character_details_incomplete|npc:GUARD|{}",
            "proposal": {
                "title": "Partial",
                "summary": "Complete traits only",
                "patches": [
                    {
                        "target_type": "npc",
                        "target_id": "GUARD",
                        "description": "Traits",
                        "field_updates": {"personality_profile": TRAITS},
                    }
                ],
            },
        },
    )
    assert response.status_code == 200, response.text
    remaining = response.json()["validation_run"]["structural_findings"]
    finding = next(
        f
        for f in remaining
        if f["code"] == "character_details_incomplete" and f["location"] == "npc:GUARD"
    )
    assert "visual_profile" in finding["context"]["missing_fields"]
    assert not any(
        field.startswith("personality_profile.") for field in finding["context"]["missing_fields"]
    )


def test_known_worn_items_require_free_protagonist_equipment_slots():
    hero = {
        "id": "hero",
        "name": "Hero",
        "description": "Traveler",
        "goal": "Travel",
        "character": "Kind",
        "equipment": {},
        "visual_profile": {"appearance": {"features": "Traveler"}, "worn": [{"item_id": "COAT"}]},
    }
    item = {
        "id": "COAT",
        "entity_type": "OBJECT",
        "item_type": "WEARABLE",
        "wearable_slots": ["Chest"],
        "clothing": OUTFIT["clothing"],
    }
    payload = {"adventure": {}, "protagonist": hero, "entities_all": [item]}
    findings = validate_adventure(payload)
    assert any(
        "equipment.worn_slots" in (f.context or {}).get("missing_fields", []) for f in findings
    )
    hero["equipment"] = {"Chest": "COAT"}
    assert not any(
        "equipment.worn_slots" in (f.context or {}).get("missing_fields", [])
        for f in validate_adventure(payload)
    )


def test_invalid_worn_shape_is_reported_without_crashing_validation():
    payload = {
        "adventure": {
            "original_manifest": {
                "nsfw_settings": {"enabled": True},
                "clothing_settings": {"detailed": True},
            }
        },
        "protagonist": {"name": "Hero", "age_years": 25, "visual_profile": {"worn": 123}},
    }
    findings = validate_adventure(payload)
    assert any(
        "visual_profile.invalid" in (f.context or {}).get("missing_fields", []) for f in findings
    )
