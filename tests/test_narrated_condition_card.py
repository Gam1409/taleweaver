"""Session-owner cards can show source-confirmed narrated facts without publishing them."""

from copy import deepcopy
from hashlib import sha256

import pytest
from sqlalchemy import select

from backend.core.text_evidence import EvidenceSpan
from backend.engine.physical_conditions.ledger import read
from backend.engine.physical_conditions.presentation import context
from backend.engine.physical_conditions.schema import Source
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_npc_condition_slots import record_parts
from tests.test_npc_current_state import URL, configure
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]
TEXT = "The narrator describes an established current medical observation."
PARTS = ["vagina", "anus", "cervix"]


async def prepare(case):
    await configure()
    await record_parts(PARTS, visibility="private")
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        npc = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.id == "NPC_NEW", WorldEntity.session_id == state.session_id
            )
        )
        npc.age_years = None if case == "unknown_age" else 17 if case == "minor" else 30
        profile = deepcopy(npc.visual_profile)
        profile["appearance"]["age_years"] = npc.age_years
        profile.pop("body", None)
        npc.visual_profile = profile
        states = deepcopy(state.entity_states)
        states["__manifest_snapshot__"]["original_manifest"].update(
            nsfw_settings={"enabled": case != "disabled"},
            clothing_settings={"detailed": case != "no_details"},
        )
        ledger = read(states)
        for row in ledger.conditions.values():
            if not row.id.startswith("slot-condition-"):
                continue
            row.latest = Source(
                kind="narration",
                message_id="private-proof",
                content_hash=sha256(TEXT.encode()).hexdigest(),
                quote=TEXT,
                **({"evidence_span": EvidenceSpan(start=0, end=4)} if case == "bad_span" else {}),
            )
            if case == "resolved":
                row.status = "resolved"
            if case == "manual":
                row.latest = Source(kind="manual", quote=TEXT)
        states["__physical_conditions__"] = ledger.model_dump()
        if case in {"absent", "hidden"}:
            states["NPC_NEW"] = {"presence": "absent"} if case == "absent" else {"is_hidden": True}
        state.entity_states = states
        if case != "missing":
            db.add(
                ChatMessage(
                    id="private-proof",
                    session_id="another-session" if case == "foreign" else state.session_id,
                    role="user" if case == "player" else "assistant",
                    is_debug=case == "debug",
                    content="The original source was edited." if case == "edited" else TEXT,
                )
            )
        await db.commit()
        return deepcopy(state.entity_states)


@pytest.mark.parametrize(
    "case",
    [
        "confirmed",
        "disabled",
        "no_details",
        "minor",
        "unknown_age",
        "missing",
        "edited",
        "foreign",
        "debug",
        "player",
        "manual",
        "resolved",
        "bad_span",
        "absent",
        "hidden",
    ],
)
async def test_only_enabled_adult_owner_view_uses_unchanged_narration(
    auth_client, portrait_world, case
):
    before = await prepare(case)
    response = await auth_client.get(URL)
    assert response.status_code == 200
    current = response.json()["current_state"]
    rows = [
        row for row in current["conditions"]["items"] if row["id"].startswith("slot-condition-")
    ]
    if case == "confirmed":
        assert [row["display_slots"] for row in rows] == [
            ["BodyVaginal"],
            ["BodyAnal"],
            ["BodyUterine"],
        ]
        assert all(
            row["visibility"] == "private" and row["observation"] == "recorded" for row in rows
        )
        assert [row["key"] for row in current["clothing"]["placement_slots"]] == [
            "BodyVaginal",
            "BodyAnal",
            "BodyUterine",
        ]
    else:
        assert rows == []
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        assert state.entity_states == before
        shared = context(state, {"NPC_NEW"}, public_only=True, known_private={"__player__"})
        assert all(not row["id"].startswith("slot-condition-") for row in shared["active"])
