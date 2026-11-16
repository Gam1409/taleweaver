"""Shared fictional authoring data for API and real-browser AI-Fix checks."""

from copy import deepcopy
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.routes.adventures.editing.payload import _build_adventure_editor_assets
from backend.core.world_validator import validate_adventure
from backend.engine.personality.profile import CATALOG
from backend.models.adventure_template import AdventureTemplate
from backend.models.avatar import Avatar
from backend.models.user import User
from backend.models.validation_run import ValidationRun
from backend.models.world_entity import WorldEntity, WorldScene

TEMPLATE = "ai-fix-fixture"
NPC = "MARA"
TRAITS = {key: next(iter(value[1])) for key, value in CATALOG.items()}


def garment(name, description, slot, layer, coverage, *, underwear=False):
    return {
        "name": name,
        "description": description,
        "wearable_slots": [slot],
        "clothing": {
            "layer": layer,
            "coverage": coverage,
            "opaque": True,
            "underwear": underwear,
            "description": description,
        },
    }


OUTFIT = [
    garment(
        "White blouse",
        "A white cotton blouse with narrow cuffs, a folded collar and pearl buttons.",
        "Chest",
        1,
        ["torso", "arms"],
    ),
    garment(
        "Black pencil skirt",
        "A black wool pencil skirt with a fitted waistband, concealed zip and neat back vent.",
        "Legs",
        1,
        ["pelvis", "legs"],
    ),
    garment(
        "Medical coat",
        "A crisp white cotton medical coat with broad lapels, deep pockets and reinforced seams.",
        "Chest",
        2,
        ["torso", "arms"],
    ),
    garment(
        "Black stockings",
        "Fine black stockings with a smooth matte knit, flat seams and elastic welt bands.",
        "Legs",
        0,
        ["legs", "feet"],
    ),
    garment(
        "Red silk bra",
        "A red silk bra with lightly structured cups, adjustable straps and a narrow satin band.",
        "Chest",
        0,
        ["torso"],
        underwear=True,
    ),
    garment(
        "Red silk briefs",
        "Red silk briefs with a soft lining, fine elastic edging and small flat side seams.",
        "Legs",
        0,
        ["pelvis"],
        underwear=True,
    ),
    garment(
        "Black shoes",
        "Black leather shoes with low block heels, rounded toes and polished stitched uppers.",
        "Feet",
        1,
        ["feet"],
    ),
]


def proposal(kind="npc", target=NPC):
    fields = {
        "appearance": {"hair": "Dark brown hair", "features": "Small freckles across the nose"},
        "outfit": deepcopy(OUTFIT),
    }
    if kind == "npc":
        fields["personality_profile"] = TRAITS
    return {
        "title": "Complete the character's outfit",
        "summary": "Create a coordinated outfit with its inner layers and preserve the character's existing identity.",
        "patches": [
            {
                "target_type": kind,
                "target_id": target,
                "description": "Register the missing garments and their layers.",
                "field_updates": fields,
            }
        ],
    }


async def seed(db: AsyncSession, owner: User, *, source="structural") -> dict:
    owner.llm_settings = {"complex_model_provider": "ollama", "complex_model": "fixture"}
    adventure = AdventureTemplate(
        id=TEMPLATE,
        owner_id=owner.id,
        title="AI Fix browser fixture",
        rule_enforcement_mode="vn",
        is_ready=True,
        language="English",
        original_manifest={
            "nsfw_settings": {"enabled": True},
            "clothing_settings": {"detailed": True},
        },
    )
    db.add(adventure)
    await db.flush()
    db.add(
        WorldScene(
            id="START",
            template_id=TEMPLATE,
            label="Clinic",
            description="A bright clinic reception.",
        )
    )
    db.add(
        WorldEntity(
            id=NPC,
            template_id=TEMPLATE,
            entity_type="NPC",
            name="Mara",
            age_years=34,
            description="An adult physician with dark hair and a precise manner.",
            goal="Prepare the clinic for the morning.",
            character="Direct, kind and independent.",
            current_scene_id="START",
            inventory=[],
        )
    )
    db.add(
        Avatar(
            user_id=owner.id,
            template_id=TEMPLATE,
            name="Traveler",
            age_years=32,
            stats={},
            description="An adult traveler with a steady gaze.",
            goal="Learn about the clinic.",
            character="Friendly and curious.",
        )
    )
    await db.flush()
    assets = await _build_adventure_editor_assets(TEMPLATE, db)
    finding = next(
        f
        for f in validate_adventure(assets)
        if f.code == "character_details_incomplete" and f.location == f"npc:{NPC}"
    )
    entries = [finding.model_dump()]
    db.add(
        ValidationRun(
            template_id=TEMPLATE,
            user_id=owner.id,
            include_ai=source == "ai",
            structural_findings=entries if source == "structural" else [],
            ai_findings=entries if source == "ai" else [],
            structural_finding_count=int(source == "structural"),
            ai_finding_count=int(source == "ai"),
            error_count=0,
            warning_count=1,
            run_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()
    return {
        "finding_code": finding.code,
        "finding_message": finding.message,
        "finding_location": finding.location,
        "finding_context": finding.context,
        "finding_severity": finding.severity,
    }
