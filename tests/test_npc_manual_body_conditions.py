"""Explicit public body corrections reach the card without inventing visual exposure."""

import json
from copy import deepcopy

import pytest
from sqlalchemy import select

from backend.engine.chpm.schema import KernelState, Settings
from backend.engine.chpm.state import KEY as PERSONALITY_KEY
from backend.engine.debug_engine import DebugEngine
from backend.engine.physical_conditions.ledger import read
from backend.engine.physical_conditions.visuals import project
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.test_npc_current_state import URL, configure
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]


@pytest.mark.parametrize("mode", ["off", "live"])
@pytest.mark.parametrize("visibility", ["public", "private"])
@pytest.mark.parametrize("kind", ["fluid", "other"])
async def test_manual_body_state_is_available_on_the_card_only_when_explicitly_public(
    auth_client, portrait_world, mode, visibility, kind
):
    await configure()
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        state.is_debug_enabled = True
        state.entity_states = {
            **state.entity_states,
            PERSONALITY_KEY: KernelState(
                settings=Settings(mode=mode, actor_ids=["NPC_NEW"])
            ).model_dump(),
        }
        revision = read(state.entity_states).revision
        minute = state.in_game_time
        command = "condition " + json.dumps(
            {
                "operation": "record",
                "target_id": "NPC_NEW",
                "kind": kind,
                "part": "skin surface",
                "detail": "A remaining moisture trace on the skin."
                if kind == "fluid"
                else "A fine tremor in the hand.",
                "visibility": visibility,
                "expected_revision": revision,
            }
        )
        result = await DebugEngine.handle_debug_command(db, state, command)
        assert result.startswith("DEBUG: Updated"), result
        await db.commit()
        ledger = read(state.entity_states)
        fluid = next(row for row in ledger.conditions.values() if row.kind == kind)
        assert fluid.latest.kind == "manual" and not fluid.visual_detail
        assert state.in_game_time == minute
        before = deepcopy(state.entity_states)
        assert not any(
            row["id"] == fluid.id
            for row in project(
                state,
                {
                    "NPC_NEW": {
                        "id": "NPC_NEW",
                        "visual_profile": {"appearance": {"age_years": 30}, "worn": []},
                        "resolved_inventory": [],
                    }
                },
                detailed=True,
            )
        )
    current = (await auth_client.get(URL)).json()["current_state"]
    displayed = [row for row in current["conditions"]["items"] if row["id"] == fluid.id]
    assert bool(displayed) is (visibility == "public")
    if displayed:
        assert displayed[0]["detail"] == fluid.detail
        assert displayed[0]["observation"] == "recorded"
    async with TestSessionLocal() as db:
        stored = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        assert stored.entity_states == before


async def test_partial_cleaning_preserves_remainder_and_does_not_clean_a_separate_internal_state(
    auth_client, portrait_world
):
    await configure()
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        state.is_debug_enabled = True
        for part, visibility in [("outer surface", "public"), ("internal region", "private")]:
            result = await DebugEngine.handle_debug_command(
                db,
                state,
                "condition "
                + json.dumps(
                    {
                        "operation": "record",
                        "target_id": "NPC_NEW",
                        "kind": "fluid",
                        "part": part,
                        "detail": f"Fluid remains in {part}.",
                        "visibility": visibility,
                        "expected_revision": read(state.entity_states).revision,
                    }
                ),
            )
            assert result.startswith("DEBUG: Updated")
        ledger = read(state.entity_states)
        outer = next(row for row in ledger.conditions.values() if row.part == "outer surface")
        inside = next(row for row in ledger.conditions.values() if row.part == "internal region")
        result = await DebugEngine.handle_debug_command(
            db,
            state,
            "condition "
            + json.dumps(
                {
                    "operation": "reduce",
                    "condition_id": outer.id,
                    "detail": "A smaller visible trace remains.",
                    "visibility": "public",
                    "expected_revision": ledger.revision,
                }
            ),
        )
        assert result.startswith("DEBUG: Updated")
        await db.commit()
        assert read(state.entity_states).conditions[inside.id] == inside
    current = (await auth_client.get(URL)).json()["current_state"]
    body = next(row for row in current["conditions"]["items"] if row["id"] == outer.id)
    assert body["status"] == "reduced" and body["detail"] == "A smaller visible trace remains."
    assert not any(row["id"] == inside.id for row in current["conditions"]["items"])
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        minute = state.in_game_time
        result = await DebugEngine.handle_debug_command(
            db,
            state,
            "condition "
            + json.dumps(
                {
                    "operation": "clean",
                    "condition_id": outer.id,
                    "expected_revision": read(state.entity_states).revision,
                }
            ),
        )
        assert result.startswith("DEBUG: Updated")
        assert state.in_game_time == minute
        assert read(state.entity_states).conditions[inside.id] == inside
        await db.commit()
    current = (await auth_client.get(URL)).json()["current_state"]
    assert not any(row["id"] in {outer.id, inside.id} for row in current["conditions"]["items"])
