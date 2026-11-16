"""Condition metadata reads the authoritative clock without advancing or freezing it."""

import pytest

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.engine.narrated_items.schema import ItemExtraction
from backend.engine.physical_conditions.ledger import read
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.test_physical_conditions import record
from tests.test_vn_time import ClockRoles
from tests.test_vn_turn_integration import final_payload, install_roles, seed_vn

NARRATION = "The hero notices an old cut on the neck."


class ConditionClockRoles(ClockRoles):
    proposals = [record(target_id="__player__", evidence=NARRATION)]

    async def structured(self, *args, **kwargs):
        result = await super().structured(*args, **kwargs)
        if isinstance(result, ItemExtraction):
            return ItemExtraction(condition_updates=self.proposals)
        return result


@pytest.mark.asyncio
async def test_same_room_clock_keeps_advancing_when_the_model_proposes_no_condition_changes(
    monkeypatch,
):
    monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", NARRATION)
    roles = ConditionClockRoles(10)
    install_roles(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _, state, _ = await seed_vn(db)
        first = [
            part
            async for part in GameTurnManager(db, "session-1", user).process_turn(
                "I wait ten minutes."
            )
        ]
        assert final_payload(first)["status"] == "success"
        row = next(iter(read(state.entity_states).conditions.values()))
        assert state.in_game_time == row.first_recorded_minute == row.last_changed_minute == 10
        identifier = row.id
        roles.proposals = []
        roles.elapsed = 20
        second = [
            part
            async for part in GameTurnManager(db, "session-1", user).process_turn(
                "I wait twenty minutes."
            )
        ]
        assert final_payload(second)["sheet"]["in_game_time"] == 30
        assert state.current_scene_id == "START"
        assert read(state.entity_states).last_check["minute"] == 30
        assert read(state.entity_states).conditions[identifier].last_changed_minute == 10
        roles.elapsed = 5
        later = [
            part
            async for part in GameTurnManager(db, "session-1", user).process_turn(
                "I wait five minutes."
            )
        ]
        assert final_payload(later)["sheet"]["in_game_time"] == 35
        assert read(state.entity_states).conditions[identifier].first_recorded_minute == 10
        assert read(state.entity_states).last_check["proposed_count"] == 0


@pytest.mark.asyncio
async def test_replay_and_reload_keep_clock_and_fact_times_in_the_restored_timeline(monkeypatch):
    monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", NARRATION)
    roles = ConditionClockRoles(10)
    install_roles(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _, state, _ = await seed_vn(db)
        first = [
            part async for part in GameTurnManager(db, "session-1", user).process_turn("Wait.")
        ]
        assert final_payload(first)["status"] == "success"
        row = next(iter(read(state.entity_states).conditions.values()))
        identifier, origin = row.id, row.origin.message_id
        treatment = "The hero disinfects the cut."
        monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", treatment)
        roles.proposals = [
            {"operation": "treat", "condition_id": identifier, "evidence": treatment}
        ]
        roles.elapsed = 20
        second = [
            part async for part in GameTurnManager(db, "session-1", user).process_turn("Treat it.")
        ]
        assert final_payload(second)["sheet"]["in_game_time"] == 30
        row = read(state.entity_states).conditions[identifier]
        assert row.first_recorded_minute == 10 and row.last_changed_minute == 30
        old_reply = row.latest.message_id
        roles.elapsed = 5
        replay = [
            part
            async for part in GameTurnManager(db, "session-1", user).process_turn(
                "ignored", replay_message_id=old_reply
            )
        ]
        assert final_payload(replay)["sheet"]["in_game_time"] == 15
        row = read(state.entity_states).conditions[identifier]
        assert row.first_recorded_minute == 10 and row.last_changed_minute == 15
        assert row.origin.message_id == origin and row.latest.message_id != old_reply
        assert await db.get(ChatMessage, old_reply) is None
        state_id = state.id
    roles.elapsed, roles.proposals = 2, []
    async with TestSessionLocal() as db:
        result = [
            part async for part in GameTurnManager(db, "session-1", user).process_turn("Continue.")
        ]
        assert final_payload(result)["sheet"]["in_game_time"] == 17
        saved = await db.get(SessionState, state_id)
        row = read(saved.entity_states).conditions[identifier]
        assert row.first_recorded_minute == 10 and row.last_changed_minute == 15
