"""Authoring repairs must remain consistent with runtime clothing and social facts."""

from copy import deepcopy

import pytest
from sqlalchemy import select

from backend.core.world_validator import validate_adventure
from backend.engine.authoring_completion import complete_character
from backend.engine.clothing.projection import visible_character
from backend.engine.visual_novel.schema import InteractionPlan, SocialProposal
from backend.engine.visual_novel.social import apply_plan
from backend.models.adventure_template import AdventureTemplate
from backend.models.avatar import Avatar
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_authoring_completion import OUTFIT
from tests.test_editor_entity_update import _seed
from tests.test_vn_social import npc, seeded


def test_inline_underwear_is_not_reported_missing_and_stays_hidden_under_coat():
    inner = {
        "id": "INNER",
        "name": "Undershirt",
        "wearable_slots": ["Chest"],
        "clothing": {"layer": 0, "coverage": ["torso"], "underwear": True},
    }
    coat = {"id": "COAT", **deepcopy(OUTFIT)}
    hero = {
        "age_years": 30,
        "inventory": [inner, coat],
        "equipment": {"Chest": coat},
        "visual_profile": {
            "appearance": {"age_years": 30, "features": "Traveler"},
            "worn": [{"item_id": "INNER"}, {"item_id": "COAT"}],
        },
    }
    findings = validate_adventure(
        {
            "adventure": {
                "original_manifest": {
                    "nsfw_settings": {"enabled": True},
                    "clothing_settings": {"detailed": True},
                }
            },
            "protagonist": hero,
        }
    )
    fields = [field for f in findings for field in (f.context or {}).get("missing_fields", [])]
    assert "outfit.inner_layers_review" not in fields
    assert "equipment.worn_slots" not in fields
    visual = visible_character(hero["visual_profile"], hero["inventory"], detailed=True)
    assert [item["item_id"] for item in visual["clothing"]] == ["COAT"]
    hero["equipment"] = {}
    findings = validate_adventure({"adventure": {}, "protagonist": hero})
    assert any(
        "equipment.worn_slots" in (f.context or {}).get("missing_fields", []) for f in findings
    )


@pytest.mark.asyncio
async def test_outfit_repair_refreshes_inline_inventory_and_equipment(auth_client, setup_test_db):
    template_id = await _seed()
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, template_id)
        actor = await db.scalar(select(Avatar).where(Avatar.template_id == template_id))
        stale = {"id": "COAT", "name": "Travel coat", "clothing": None}
        actor.inventory = [deepcopy(stale)]
        actor.equipment = {"Chest": deepcopy(stale)}
        db.add(
            WorldEntity(
                id="COAT",
                template_id=template_id,
                entity_type="OBJECT",
                name="Travel coat",
                description="A gray wool coat.",
                item_type="WEARABLE",
                current_scene_id="INVENTORY",
                is_in_inventory=True,
            )
        )
        await db.flush()
        await complete_character(
            db,
            adventure,
            actor,
            {"appearance": {"features": "Traveler"}, "outfit": [{**OUTFIT, "item_id": "COAT"}]},
        )
        await db.commit()
        await db.refresh(actor)
        assert actor.inventory[0]["clothing"]["layer"] == 2
        assert actor.equipment["Chest"]["clothing"]["layer"] == 2
        assert len(actor.inventory) == 1
        visible = visible_character(
            actor.visual_profile, actor.inventory, equipment=actor.equipment
        )
        assert [item["item_id"] for item in visible["clothing"]] == ["COAT"]


@pytest.mark.parametrize("source", ["scene_context", "player_action"])
def test_omitted_social_direction_does_not_reset_known_emotion_or_intention(source):
    social, character = seeded()
    character.emotion = "angry"
    character.emotion_cause = "Earlier conflict."
    character.emotion_source_message_id = "OLD"
    character.next_intention = "set_boundary"
    observed = SocialProposal(
        npc_id="LINA",
        source=source,
        evidence="I ask about the library.",
        basis="performed_interaction",
    )
    plan = InteractionPlan(
        completed_events=[observed] if source == "scene_context" else [],
        reactions=[observed] if source == "player_action" else [],
    )
    directed = apply_plan(social, plan, [npc()], observed.evidence, observed.evidence, "NEW")
    for state in (character, directed.characters["LINA"]):
        assert state.emotion == "angry"
        assert state.emotion_cause == "Earlier conflict."
        assert state.emotion_source_message_id == "OLD"
        assert state.next_intention == "set_boundary"


def test_explicit_neutral_emotion_can_replace_previous_feeling():
    social, character = seeded()
    character.emotion = "angry"
    observation = SocialProposal(
        npc_id="LINA",
        source="scene_context",
        evidence="Lina calmed down.",
        basis="performed_interaction",
        emotion="neutral",
    )
    apply_plan(
        social,
        InteractionPlan(completed_events=[observation]),
        [npc()],
        "",
        observation.evidence,
        "NEW",
    )
    assert character.emotion == "neutral"
    assert character.emotion_source_message_id == "NEW"
