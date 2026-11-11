"""Equipment cards read canonical placements without models or a second inventory."""

from copy import deepcopy
from hashlib import sha256

import pytest
from sqlalchemy import select

from backend.engine.clothing.equipment_view import display_slots, layout
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_npc_current_state import URL, configure, update_override
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]
TEXT = "Lina lowers her shirt to her waist and places the sensor in its body slot."


async def place(*, source_case="confirmed", attachment=False):
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        npc = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == state.session_id, WorldEntity.id == "NPC_NEW"
            )
        )
        profile = deepcopy(npc.visual_profile)
        proof = {
            "source_message_id": "placement",
            "content_hash": sha256(TEXT.encode()).hexdigest(),
            "evidence": TEXT,
        }
        if source_case == "bad_span":
            proof["evidence_span"] = {"start": 0, "end": 4}
        profile["worn"][1].update(uncovered_regions=["torso", "arms"], source=proof)
        if attachment:
            profile["body"] = {"form": "humanoid", "attachment_slots": ["anal"]}
            profile["worn"].append(
                {"item_id": "SENSOR", "attachment_slot": "anal", "source": proof}
            )
            npc.inventory = [*npc.inventory, {"id": "SENSOR", "name": "Sealed sensor"}]
        state.entity_states = {
            **state.entity_states,
            "NPC_NEW": {**state.entity_states["NPC_NEW"], "visual_profile": profile},
        }
        if source_case != "missing":
            db.add(
                ChatMessage(
                    id="placement",
                    session_id="other-session"
                    if source_case == "other_session"
                    else state.session_id,
                    role="assistant",
                    content="An edited message." if source_case == "edited" else TEXT,
                )
            )
        await db.commit()
        return deepcopy(state.entity_states)


@pytest.mark.parametrize(
    "source_case", ["confirmed", "edited", "missing", "other_session", "bad_span"]
)
async def test_fully_displaced_wear_stays_known_only_with_its_original_source(
    auth_client, portrait_world, source_case
):
    await configure()
    before = await place(source_case=source_case)
    data = (await auth_client.get(URL)).json()["current_state"]
    shirt = [item for item in data["clothing"]["items"] if item["item_id"] == "SHIRT"]
    assert bool(shirt) is (source_case == "confirmed")
    if shirt:
        assert shirt[0]["slots"] == ["Chest"]
        assert shirt[0]["uncovered_regions"] == ["torso", "arms"]
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        assert state.entity_states == before


async def test_body_slot_appears_only_for_confirmed_occupied_item_and_disappears_after_removal(
    auth_client, portrait_world
):
    await configure()
    await place(attachment=True)
    data = (await auth_client.get(URL)).json()["current_state"]
    sensor = next(item for item in data["clothing"]["items"] if item["item_id"] == "SENSOR")
    assert sensor["slots"] == ["BodyAnal"] and not sensor["visible_regions"]
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        profile = deepcopy(state.entity_states["NPC_NEW"]["visual_profile"])
    profile["worn"] = [item for item in profile["worn"] if item["item_id"] != "SENSOR"]
    await update_override(visual_profile=profile)
    empty = (await auth_client.get(URL)).json()["current_state"]
    assert not any("BodyAnal" in item["slots"] for item in empty["clothing"]["items"])


@pytest.mark.parametrize(
    "kind,gender,body,form,variant",
    [
        ("HUMANOID", "Female", None, "humanoid", "female"),
        ("HUMANOID", "мужской", None, "humanoid", "male"),
        ("HUMANOID", None, None, "humanoid", "neutral"),
        ("ANIMAL", "Female", None, "non_humanoid", "female"),
        ("BEING", None, None, "unknown", "neutral"),
        ("HUMANOID", "Female", {"form": "non_humanoid"}, "non_humanoid", "female"),
        ("MONSTER", "Female", {"form": "humanoid", "silhouette": "neutral"}, "humanoid", "neutral"),
    ],
)
def test_body_shape_and_gender_are_separate(kind, gender, body, form, variant):
    profile = {"body": body} if body is not None else None
    assert layout(profile, gender=gender, npc_type=kind) == {"form": form, "silhouette": variant}


def test_existing_slot_aliases_and_alternatives_preserve_one_presentation_position():
    assert display_slots(["ring_2", "ring_1"], []) == ["Ring_2"]
    assert display_slots(["unknown"], ["feet"]) == ["Feet"]
    assert display_slots(None, ["torso", "arms"]) == ["Chest"]


@pytest.mark.parametrize(
    "detailed,age,shown",
    [(True, 30, True), (False, 30, False), (True, 17, False), (True, None, False)],
)
async def test_known_displaced_underwear_still_respects_detail_and_age(
    auth_client, portrait_world, detailed, age, shown
):
    await configure()
    await place()
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        npc = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == state.session_id, WorldEntity.id == "NPC_NEW"
            )
        )
        profile = deepcopy(state.entity_states["NPC_NEW"]["visual_profile"])
        profile["appearance"]["age_years"] = age
        profile["worn"][2].update(uncovered_regions=["pelvis"], source=profile["worn"][1]["source"])
        npc.age_years = age
        # Clearing the editor's age also clears its legacy appearance fallback.
        npc.visual_profile = {
            **npc.visual_profile,
            "appearance": {**npc.visual_profile["appearance"], "age_years": age},
        }
        states = deepcopy(state.entity_states)
        states["NPC_NEW"]["visual_profile"] = profile
        states["__manifest_snapshot__"]["original_manifest"]["clothing_settings"]["detailed"] = (
            detailed
        )
        state.entity_states = states
        await db.commit()
    items = (await auth_client.get(URL)).json()["current_state"]["clothing"]["items"]
    assert any(row["item_id"] == "UNDERWEAR" for row in items) is shown


async def test_invalid_displacement_does_not_bypass_conservative_projection(
    auth_client, portrait_world
):
    await configure()
    await place()
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        profile = deepcopy(state.entity_states["NPC_NEW"]["visual_profile"])
    profile["worn"][1]["uncovered_regions"] = ["torso", "arms", "feet"]
    await update_override(visual_profile=profile)
    items = (await auth_client.get(URL)).json()["current_state"]["clothing"]["items"]
    assert not any(row["item_id"] == "SHIRT" for row in items)
