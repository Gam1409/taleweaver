"""Travel acknowledgment checks the actual movement owner and rolls back failed writes."""

from copy import deepcopy

import pytest
from sqlalchemy import func, select

from backend.engine.npc_actions import postconditions, publication
from backend.engine.npc_actions.contracts import Move
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.test_npc_action_movement import movement_fixture
from tests.test_npc_two_phase_postconditions import approve


@pytest.mark.parametrize("reverse,bidirectional", [(False, False), (True, True)])
async def test_verified_move_keeps_player_and_clock_and_clears_origin_position(
    reverse, bidirectional
):
    async with TestSessionLocal() as db:
        host, _, _, _, draft = await movement_fixture(
            db, reverse=reverse, bidirectional=bidirectional
        )
        approve(draft, Move(tool="move_to", destination_scene_id="ANNEX"))
        [result] = await publication.publish(host, draft, verify_postconditions=True)
        assert result["status"] == "applied"
        await db.commit()
        await db.refresh(host.state)
        assert host.state.current_scene_id == "START" and host.state.in_game_time == 23
        assert host.state.entity_states["LINA"]["current_scene_id"] == "ANNEX"
        assert host.state.entity_states["LINA"]["presence"] == "present"
        assert host.state.entity_states["LINA"]["spatial_position"] is None


@pytest.mark.parametrize(
    "fault",
    [
        "skip",
        "missing_overlay",
        "location",
        "absent",
        "invalid_presence",
        "position",
        "missing_position",
        "missing_actor",
        "clock",
    ],
)
async def test_corrupt_movement_rolls_back_world_and_messages_before_success(monkeypatch, fault):
    async with TestSessionLocal() as db:
        host, actor, _, _, draft = await movement_fixture(db)
        approve(draft, Move(tool="move_to", destination_scene_id="ANNEX"))
        before = deepcopy(host.state.entity_states)
        messages_before = await db.scalar(select(func.count()).select_from(ChatMessage))
        apply = publication._apply

        async def broken_move(manager, scope, request, preview):
            if fault == "skip":
                return
            await apply(manager, scope, request, preview)
            states = deepcopy(manager.state.entity_states)
            if fault == "missing_overlay":
                states.pop("LINA")
            elif fault == "location":
                states["LINA"]["current_scene_id"] = "VAULT"
            elif fault == "absent":
                states["LINA"]["presence"] = "absent"
            elif fault == "invalid_presence":
                states["LINA"]["presence"] = "invalid"
            elif fault == "position":
                states["LINA"]["spatial_position"] = "beside the original shelves"
            elif fault == "missing_position":
                states["LINA"].pop("spatial_position")
            elif fault == "missing_actor":
                await db.delete(actor)
            else:
                manager.state.in_game_time += 1
            manager.state.entity_states = states

        monkeypatch.setattr(publication, "_apply", broken_move)
        with pytest.raises(postconditions.PostconditionViolationError):
            async with db.begin_nested():
                await publication.publish(host, draft, verify_postconditions=True)
        await db.refresh(host.state)
        assert host.state.entity_states == before
        assert host.state.current_scene_id == "START" and host.state.in_game_time == 23
        assert await db.scalar(select(func.count()).select_from(ChatMessage)) == messages_before
        assert draft.published_results is None
