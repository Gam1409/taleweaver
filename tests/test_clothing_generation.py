"""Generation keeps clothing canonical, opt-in, age-bounded and backward compatible."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.api.routes.adventures.adventure_creation import CoverSource, build_template
from backend.api.routes.adventures.schemas import CreateAdventureTemplatePayload
from backend.engine.clothing.generation import generation_instruction, normalize_manifest_clothing
from backend.engine.clothing.settings import clothing_settings, preserve_clothing_settings
from backend.engine.manifest_apply.adventure_meta import apply_final_adventure_fields
from backend.engine.staged_world.schemas import ProtagonistDetail, batch_schema
from backend.engine.staged_world.validation import _validate_holder
from backend.engine.world_schemas import (
    ProtagonistSchema,
    WorldManifesto,
    WorldNPCSchema,
    WorldObjectSchema,
)


def garment(layer=2, underwear=False):
    return {
        "layer": layer,
        "coverage": ["torso"],
        "opaque": True,
        "underwear": underwear,
        "description": "Plain cloth",
    }


def profile(item_id="COAT", age=26):
    return {
        "version": 1,
        "appearance": {"age_years": age, "hair": "Brown hair"},
        "worn": [{"item_id": item_id, "uncovered_regions": []}],
    }


def clothing_manifest():
    return {
        "protagonist": {
            "name": "Hero",
            "starting_inventory": ["COAT"],
            "starting_equipment": {},
            "visual_profile": profile(),
        },
        "npcs": [
            {
                "id": "NURSE",
                "name": "Lina",
                "inventory": ["DRESS"],
                "visual_profile": profile("DRESS", age=31),
            }
        ],
        "objects": [
            {"id": "COAT", "name": "Travel coat", "clothing": garment()},
            {"id": "DRESS", "name": "Everyday dress", "clothing": garment()},
        ],
    }


@pytest.mark.parametrize("enabled", [False, True])
def test_author_setting_survives_generation_and_cannot_be_changed_by_the_model(enabled):
    payload = CreateAdventureTemplatePayload(title="Clothes", detailed_clothing=enabled)
    template = build_template(payload, "world", "owner", CoverSource())
    assert clothing_settings(template.original_manifest) == {"detailed": enabled}
    malicious = {"clothing_settings": {"detailed": not enabled}, "plot": "Generated plot"}
    assert preserve_clothing_settings(malicious, template)["clothing_settings"] == {
        "detailed": enabled
    }
    apply_final_adventure_fields(SimpleNamespace(adventure=template, manifest=malicious))
    assert clothing_settings(template.original_manifest) == {"detailed": enabled}
    instruction = generation_instruction(template.original_manifest)
    assert "individually" in instruction and "single owner" in instruction
    assert ("explicitly established" in instruction) if enabled else ("disabled" in instruction)


@pytest.mark.parametrize(
    "raw",
    [None, {}, {"clothing_settings": {"detailed": "true"}}, {"clothing_settings": {"detailed": 1}}],
)
def test_legacy_or_invalid_settings_default_to_outer_clothes(raw):
    assert clothing_settings(raw) == {"detailed": False}


def test_initial_profiles_reference_canonical_owned_objects_without_duplicates():
    manifest = clothing_manifest()
    manifest["protagonist"]["visual_profile"]["worn"].append({"item_id": "DRESS"})
    normalize_manifest_clothing(manifest, detailed=False)
    assert [entry["item_id"] for entry in manifest["protagonist"]["visual_profile"]["worn"]] == [
        "COAT"
    ]
    assert [entry["item_id"] for entry in manifest["npcs"][0]["visual_profile"]["worn"]] == [
        "DRESS"
    ]
    assert len(manifest["objects"]) == 2
    assert manifest["objects"][0]["metadata_json"]["clothing"] == garment()
    assert manifest["protagonist"]["starting_inventory"] == ["COAT"]


@pytest.mark.parametrize(
    "age,detailed,tracked",
    [
        (26, True, True),
        (18, True, True),
        (17, True, False),
        (None, True, False),
        (26, False, False),
    ],
)
def test_underwear_tracking_requires_explicit_adult_age_and_author_opt_in(age, detailed, tracked):
    manifest = clothing_manifest()
    manifest["protagonist"]["visual_profile"]["appearance"]["age_years"] = age
    manifest["objects"][0]["clothing"] = garment(layer=0, underwear=True)
    normalize_manifest_clothing(manifest, detailed=detailed)
    assert bool(manifest["protagonist"]["visual_profile"]["worn"]) is tracked
    # Disabling tracking never deletes an actual inventory object.
    assert manifest["protagonist"]["starting_inventory"] == ["COAT"]
    assert len(manifest["objects"]) == 2


def test_legacy_manifest_does_not_acquire_fabricated_profiles_or_clothes():
    manifest = {"protagonist": {"name": "Hero"}, "npcs": [{"id": "BIRD"}], "objects": []}
    before = deepcopy(manifest)
    normalize_manifest_clothing(manifest, detailed=True)
    assert manifest == before


def test_generation_contracts_support_optional_shared_profiles_in_every_mode():
    for schema in (
        ProtagonistSchema,
        WorldNPCSchema,
        ProtagonistDetail,
        batch_schema("npcs"),
        WorldManifesto,
    ):
        assert "VisualProfile" in str(schema.model_json_schema())
    assert "Garment" in str(WorldObjectSchema.model_json_schema())
    assert ProtagonistSchema.model_fields["visual_profile"].default is None
    assert WorldNPCSchema.model_fields["visual_profile"].default is None
    assert WorldObjectSchema.model_fields["clothing"].default is None


def test_staged_detail_cannot_wear_another_characters_clothing():
    plan = {
        "objects": [{"id": "COAT", "owner_id": "PROTAGONIST"}, {"id": "DRESS", "owner_id": "LINA"}]
    }
    actor = {
        "starting_inventory": ["COAT"],
        "starting_equipment": {},
        "visual_profile": profile("DRESS"),
    }
    with pytest.raises(ValueError, match="own canonical items"):
        _validate_holder("PROTAGONIST", actor, plan)


def test_profile_duplicate_items_are_rejected_by_the_structured_contract():
    from backend.engine.clothing.schema import VisualProfile

    raw = profile()
    raw["worn"].append({"item_id": "COAT"})
    with pytest.raises(ValidationError):
        VisualProfile.model_validate(raw)


def test_reapplying_legacy_actor_does_not_retain_a_previous_worlds_outfit():
    from backend.engine.manifest_apply.avatar import _update_avatar
    from backend.models.avatar import Avatar

    avatar = Avatar(visual_profile=profile())
    _update_avatar(avatar, {"name": "Legacy hero"}, {})
    assert avatar.visual_profile is None


@pytest.mark.parametrize("mode", ["rpg", "chat", "unknown"])
def test_existing_game_modes_receive_no_new_clothing_generation_policy(mode):
    assert generation_instruction({"clothing_settings": {"detailed": True}}, mode=mode) == ""
