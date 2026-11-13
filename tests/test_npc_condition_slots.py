"""Condition hover positions reuse exact canonical part identifiers without changing facts."""

from copy import deepcopy
from hashlib import sha256

import pytest
from sqlalchemy import select

from backend.engine.physical_conditions.ledger import read
from backend.engine.physical_conditions.schema import Condition, Source
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.test_npc_current_state import URL, configure, update_override
from tests.test_npc_placement_slots import body
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]
BODY_GROUPS = ["vaginal", "anal", "uterine", "penile"]
GROUP_PARTS = [
    ("clitoris", "BodyVaginal"),
    ("labia", "BodyVaginal"),
    ("vagina", "BodyVaginal"),
    ("sphincter", "BodyAnal"),
    ("anus", "BodyAnal"),
    ("uterus", "BodyUterine"),
    ("penis", "BodyPenile"),
    ("testicles", "BodyPenile"),
]


async def record_parts(parts, *, target="NPC_NEW", visibility="public", status="active"):
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        ledger = read(state.entity_states)
        source = Source(kind="manual", quote="Explicit recorded condition.")
        for index, part in enumerate(parts):
            identifier = f"slot-condition-{index}"
            ledger.conditions[identifier] = Condition(
                id=identifier,
                target_id=target,
                kind="other",
                part=part,
                detail="A recorded current condition.",
                status=status,
                visibility=visibility,
                origin=source,
                latest=source,
                updated_revision=ledger.revision,
                last_changed_minute=480,
            )
        state.entity_states = {
            **state.entity_states,
            "__physical_conditions__": ledger.model_dump(),
        }
        await db.commit()
        return deepcopy(state.entity_states)


async def projected(auth_client):
    current = (await auth_client.get(URL)).json()["current_state"]
    return [
        row for row in current["conditions"]["items"] if row["id"].startswith("slot-condition-")
    ]


async def test_grouped_parts_keep_their_identifiers_and_exactly_four_display_groups(
    auth_client, portrait_world
):
    await configure()
    await body(slots=BODY_GROUPS)
    before = await record_parts([part for part, _ in GROUP_PARTS])
    rows = await projected(auth_client)
    assert [(row["part"], row["display_slots"]) for row in rows] == [
        (part, [slot]) for part, slot in GROUP_PARTS
    ]
    assert len({slot for row in rows for slot in row["display_slots"]}) == 4
    assert all(row["last_changed_minute"] == 480 for row in rows)
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        assert state.entity_states == before


@pytest.mark.parametrize("age,detailed", [(None, True), (17, True), (30, False)])
async def test_group_metadata_is_hidden_when_details_are_unavailable(
    auth_client, portrait_world, age, detailed
):
    await configure()
    await body(slots=BODY_GROUPS, age=age, detailed=detailed)
    await record_parts(["uterus", "arm"])
    rows = await projected(auth_client)
    assert "display_slots" not in rows[0]
    assert rows[1]["display_slots"] == ["Arms"]


@pytest.mark.parametrize("slots", [[], ["anal"]])
async def test_a_condition_does_not_declare_an_unavailable_group(
    auth_client, portrait_world, slots
):
    await configure()
    await body(slots=slots)
    await record_parts(["uterus"])
    rows = await projected(auth_client)
    assert len(rows) == 1 and "display_slots" not in rows[0]


async def test_reported_regions_work_without_items_or_a_complete_body_declaration(
    auth_client, portrait_world
):
    await configure()
    await body(slots=None)
    await record_parts(["uterus", "testicles"])
    current = (await auth_client.get(URL)).json()["current_state"]
    rows = [
        row for row in current["conditions"]["items"] if row["id"].startswith("slot-condition-")
    ]
    assert [row["display_slots"] for row in rows] == [["BodyUterine"], ["BodyPenile"]]
    assert current["clothing"]["placement_status"] == "unassessed"
    assert current["clothing"]["placement_slots"] == [
        {"key": "BodyUterine", "status": "empty"},
        {"key": "BodyPenile", "status": "empty"},
    ]
    assert not any(
        any(key.startswith("Body") for key in row["slots"]) for row in current["clothing"]["items"]
    )


@pytest.mark.parametrize(
    "source_case", ["confirmed", "edited", "missing", "other_session", "debug"]
)
async def test_only_current_public_original_sources_establish_reported_regions(
    auth_client, portrait_world, source_case
):
    await configure()
    await body(slots=None)
    await record_parts(["uterus"])
    text = "An explicit current condition is recorded for the configured region."
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        ledger = read(state.entity_states)
        row = ledger.conditions["slot-condition-0"]
        row.latest = Source(
            kind="narration",
            message_id="condition-proof",
            content_hash=sha256(text.encode()).hexdigest(),
            quote=text,
        )
        # A pre-existing surface projection alone must not authorize a new group.
        row.visual_detail, row.visual_region = "A recorded trace.", "arms"
        state.entity_states = {
            **state.entity_states,
            "__physical_conditions__": ledger.model_dump(),
        }
        if source_case != "missing":
            db.add(
                ChatMessage(
                    id="condition-proof",
                    session_id="other-session"
                    if source_case == "other_session"
                    else state.session_id,
                    role="assistant",
                    content="The source was edited." if source_case == "edited" else text,
                    is_debug=source_case == "debug",
                )
            )
        await db.commit()
    current = (await auth_client.get(URL)).json()["current_state"]
    slots = current["clothing"]["placement_slots"]
    assert slots == (
        [{"key": "BodyUterine", "status": "empty"}] if source_case == "confirmed" else []
    )
    condition = next(
        row for row in current["conditions"]["items"] if row["id"] == "slot-condition-0"
    )
    assert ("display_slots" in condition) is (source_case == "confirmed")


async def test_standard_aliases_work_without_detailed_body_metadata(auth_client, portrait_world):
    await configure()
    await body(age=17, detailed=False)
    parts = ["head", "neck", "chest", "left arm", "right_hand", "left leg", "feet"]
    await record_parts(parts)
    assert [row["display_slots"] for row in await projected(auth_client)] == [
        ["Head"],
        ["Head"],
        ["Chest"],
        ["Arms"],
        ["Hands"],
        ["Legs"],
        ["Feet"],
    ]


async def test_unknown_parts_and_item_targets_remain_general_without_prose_guessing(
    auth_client, portrait_world
):
    await configure()
    await body(slots=BODY_GROUPS)
    await record_parts(["unknown", "pain in uterus", "arm and leg", "outer surface"])
    assert all("display_slots" not in row for row in await projected(auth_client))
    await record_parts(["uterus"], target="COAT")
    assert all("display_slots" not in row for row in await projected(auth_client))


@pytest.mark.parametrize("visibility,status", [("private", "active"), ("public", "resolved")])
async def test_group_mapping_does_not_expose_private_or_resolved_conditions(
    auth_client, portrait_world, visibility, status
):
    await configure()
    await body(slots=BODY_GROUPS)
    await record_parts(["uterus"], visibility=visibility, status=status)
    assert await projected(auth_client) == []
    await update_override(presence="absent")
    assert await projected(auth_client) == []
