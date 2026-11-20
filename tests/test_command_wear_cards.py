"""Source-valid commanded placements use existing character-card disclosure gates."""

from copy import deepcopy
from hashlib import sha256
from typing import get_args

import pytest
from sqlalchemy import select

from backend.engine.clothing.body_schema import (
    BODY_SLOT_KEYS,
    BodySlot,
    WearCommandProof,
    WearSource,
)
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_npc_current_state import URL, configure
from tests.test_npc_equipment import place
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]
TEXT = "I wait for the visitor's next action."
SLOT = get_args(BodySlot)[0]


async def install(
    *, source_case="confirmed", item="SHIRT", attachment=False, age=30, detailed=True, allowed=None
):
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        npc = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == state.session_id, WorldEntity.id == "NPC_NEW"
            )
        )
        message = ChatMessage(
            id="command-wear-input",
            session_id="other-session" if source_case == "other_session" else state.session_id,
            role="user",
            content=TEXT,
        )
        if source_case != "missing":
            db.add(message)
            await db.flush()
        proof = WearCommandProof(
            command_id="command-wear",
            actor_id="OTHER" if source_case == "wrong_actor" else "NPC_NEW",
            item_id="COAT" if source_case == "wrong_item" else item,
            input_id=message.id,
            input_hash=sha256(TEXT.encode()).hexdigest(),
            input_revision=message.revision_id,
            request_hash="a" * 64,
            operation="attach_item" if attachment else "adjust_clothing",
        )
        source = WearSource.from_command(proof).model_dump()
        profile = deepcopy(npc.visual_profile)
        profile["appearance"]["age_years"] = age
        npc.age_years = age
        npc.visual_profile = deepcopy(profile)
        if attachment:
            profile["body"] = {"form": "humanoid", "attachment_slots": allowed}
            profile["worn"].append({"item_id": item, "attachment_slot": SLOT, "source": source})
            npc.inventory = [*npc.inventory, {"id": item, "name": "A sealed sensor"}]
        else:
            row = next(row for row in profile["worn"] if row["item_id"] == item)
            row.update(
                uncovered_regions=["pelvis"] if item == "UNDERWEAR" else ["torso", "arms"],
                source=source,
            )
        state.entity_states = {
            **state.entity_states,
            "NPC_NEW": {**state.entity_states.get("NPC_NEW", {}), "visual_profile": profile},
            "__manifest_snapshot__": {
                "original_manifest": {"clothing_settings": {"detailed": detailed}}
            },
        }
        if source_case == "edited_input":
            message.content = "Edited input."
        db.add(
            ChatMessage(
                id="unrelated-reply",
                session_id=state.session_id,
                role="assistant",
                content="A revised narrative explanation.",
            )
        )
        await db.commit()


@pytest.mark.parametrize(
    "source_case",
    ["confirmed", "missing", "edited_input", "other_session", "wrong_actor", "wrong_item"],
)
async def test_displaced_command_wear_uses_its_real_input_and_binding(
    auth_client, portrait_world, source_case
):
    await configure()
    await install(source_case=source_case)
    response = await auth_client.get(URL)
    assert response.status_code == 200, response.text
    items = response.json()["current_state"]["clothing"]["items"]
    shirts = [row for row in items if row["item_id"] == "SHIRT"]
    assert bool(shirts) is (source_case == "confirmed")
    if shirts:
        assert shirts[0]["uncovered_regions"] == ["torso", "arms"]


@pytest.mark.parametrize(
    "age,detailed,shown",
    [(30, True, True), (17, True, False), (None, True, False), (30, False, False)],
)
async def test_command_proof_does_not_bypass_age_or_detail_for_displaced_inner_layers(
    auth_client, portrait_world, age, detailed, shown
):
    await configure()
    await install(item="UNDERWEAR", age=age, detailed=detailed)
    items = (await auth_client.get(URL)).json()["current_state"]["clothing"]["items"]
    assert any(row["item_id"] == "UNDERWEAR" for row in items) is shown


@pytest.mark.parametrize(
    "age,detailed,allowed,shown",
    [
        (30, True, [SLOT], True),
        (17, True, [SLOT], False),
        (None, True, [SLOT], False),
        (30, False, [SLOT], True),
        (30, True, [], False),
    ],
)
async def test_command_body_placement_keeps_existing_layout_and_disclosure_gates(
    auth_client, portrait_world, age, detailed, allowed, shown
):
    await configure()
    await install(item="SENSOR", attachment=True, age=age, detailed=detailed, allowed=allowed)
    clothing = (await auth_client.get(URL)).json()["current_state"]["clothing"]
    sensors = [row for row in clothing["items"] if row["item_id"] == "SENSOR"]
    assert bool(sensors) is shown
    if sensors:
        assert sensors[0]["slots"] == [BODY_SLOT_KEYS[SLOT]]


async def test_optional_detail_layout_does_not_erase_a_source_confirmed_possession(
    auth_client, portrait_world
):
    await configure()
    await place(attachment=True)
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        current = deepcopy(state.entity_states)
        current["__manifest_snapshot__"]["original_manifest"]["clothing_settings"]["detailed"] = (
            False
        )
        state.entity_states = current
        await db.commit()
    clothing = (await auth_client.get(URL)).json()["current_state"]["clothing"]
    assert any(row["item_id"] == "SENSOR" for row in clothing["items"])
    assert "placement_slots" not in clothing and "placement_status" not in clothing


async def test_editing_narration_does_not_revoke_a_commanded_current_placement(
    auth_client, portrait_world
):
    await configure()
    await install()
    async with TestSessionLocal() as db:
        reply = await db.get(ChatMessage, "unrelated-reply")
        reply.content = "Another rendering of the scene."
        await db.commit()
    items = (await auth_client.get(URL)).json()["current_state"]["clothing"]["items"]
    assert any(
        row["item_id"] == "SHIRT" and row["uncovered_regions"] == ["torso", "arms"] for row in items
    )
