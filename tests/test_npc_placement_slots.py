"""Declared placement regions are visible without inventing anatomy or inventory."""

from copy import deepcopy
from typing import get_args

import pytest
from sqlalchemy import select

from backend.engine.clothing.body_schema import BodySlot
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_npc_current_state import URL, configure, update_override
from tests.test_npc_equipment import place
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]
SLOTS = get_args(BodySlot)


async def body(*, slots=None, age=30, detailed=True):
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
        profile["appearance"]["age_years"] = age
        profile["body"] = {"form": "humanoid", "attachment_slots": slots}
        npc.visual_profile = profile
        npc.age_years = age
        state.entity_states = {
            **state.entity_states,
            "__manifest_snapshot__": {
                "original_manifest": {"clothing_settings": {"detailed": detailed}}
            },
        }
        await db.commit()
        return deepcopy(state.entity_states)


@pytest.mark.parametrize(
    "slots,status,count",
    [
        (None, "unassessed", 0),
        ([], "unavailable", 0),
        ([SLOTS[0]], "available", 1),
        (list(SLOTS), "available", 4),
    ],
)
async def test_known_empty_regions_are_projected_without_items(
    auth_client, portrait_world, slots, status, count
):
    await configure()
    before = await body(slots=slots)
    response = await auth_client.get(URL)
    assert response.status_code == 200
    clothing = response.json()["current_state"]["clothing"]
    assert clothing["placement_status"] == status
    assert len(clothing["placement_slots"]) == count
    assert all(slot["status"] == "empty" for slot in clothing["placement_slots"])
    assert not any(
        any(key.startswith("Body") for key in item["slots"]) for item in clothing["items"]
    )
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        assert state.entity_states == before


@pytest.mark.parametrize("age,detailed", [(None, True), (17, True), (30, False)])
async def test_unavailable_details_do_not_reveal_extra_regions(
    auth_client, portrait_world, age, detailed
):
    await configure()
    await body(slots=list(SLOTS), age=age, detailed=detailed)
    clothing = (await auth_client.get(URL)).json()["current_state"]["clothing"]
    assert "placement_slots" not in clothing
    assert "placement_status" not in clothing


@pytest.mark.parametrize(
    "source_case,expected",
    [
        ("confirmed", "occupied"),
        ("edited", "unconfirmed"),
        ("missing", "unconfirmed"),
        ("other_session", "unconfirmed"),
        ("bad_span", "unconfirmed"),
    ],
)
async def test_recorded_but_unconfirmed_placement_is_not_presented_as_empty(
    auth_client, portrait_world, source_case, expected
):
    await configure()
    await place(source_case=source_case, attachment=True)
    data = (await auth_client.get(URL)).json()["current_state"]
    slots = data["clothing"]["placement_slots"]
    assert len(slots) == 1 and slots[0]["status"] == expected
    sensor = [row for row in data["clothing"]["items"] if row["item_id"] == "SENSOR"]
    assert bool(sensor) is (source_case == "confirmed")
    if source_case != "confirmed":
        assert "Sealed sensor" not in str(data)


async def test_departed_character_does_not_reveal_placement_metadata(auth_client, portrait_world):
    await configure()
    await body(slots=list(SLOTS))
    await update_override(current_scene_id="OTHER")
    data = (await auth_client.get(URL)).json()["current_state"]
    assert data["availability"] == "not_present"
    assert "placement_slots" not in data["clothing"]


@pytest.mark.parametrize("slot,key", [("uterine", "BodyUterine"), ("penile", "BodyPenile")])
async def test_additional_explicit_regions_keep_source_confirmation(
    auth_client, portrait_world, slot, key
):
    await configure()
    await place(attachment=True)
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        profile = deepcopy(state.entity_states["NPC_NEW"]["visual_profile"])
    profile["body"]["attachment_slots"] = [slot]
    profile["worn"][-1]["attachment_slot"] = slot
    await update_override(visual_profile=profile)
    clothing = (await auth_client.get(URL)).json()["current_state"]["clothing"]
    assert clothing["placement_slots"] == [{"key": key, "status": "occupied"}]
    sensor = next(row for row in clothing["items"] if row["item_id"] == "SENSOR")
    assert sensor["slots"] == [key]


@pytest.mark.parametrize(
    "allowed,source_case,status,slots",
    [
        (None, "confirmed", "unassessed", [{"key": "BodyAnal", "status": "occupied"}]),
        (None, "edited", "unassessed", []),
        ([], "confirmed", "unavailable", []),
        (["vaginal"], "confirmed", "available", [{"key": "BodyVaginal", "status": "empty"}]),
    ],
)
async def test_declarations_and_current_proof_control_exposed_regions(
    auth_client, portrait_world, allowed, source_case, status, slots
):
    await configure()
    await place(source_case=source_case, attachment=True)
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        profile = deepcopy(state.entity_states["NPC_NEW"]["visual_profile"])
    profile["body"]["attachment_slots"] = allowed
    await update_override(visual_profile=profile)
    clothing = (await auth_client.get(URL)).json()["current_state"]["clothing"]
    assert clothing["placement_status"] == status
    assert clothing["placement_slots"] == slots
    if allowed is not None:
        assert "SENSOR" not in str(clothing)


async def test_lost_ownership_removes_stale_binding_without_inventing_occupancy(
    auth_client, portrait_world
):
    await configure()
    await place(attachment=True)
    await update_override(inventory=["COAT", "SHIRT", "UNDERWEAR"])
    clothing = (await auth_client.get(URL)).json()["current_state"]["clothing"]
    assert clothing["placement_slots"] == [{"key": "BodyAnal", "status": "empty"}]
    assert "SENSOR" not in str(clothing)
