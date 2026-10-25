"""VN elapsed time survives same-room actions, caps, boundaries and streamed state."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.api.routes.adventures.turn_pass_flow import advance_in_game_turn
from backend.engine.memory_manager import MemoryManager
from backend.engine.rule_engine import GameEvent
from backend.engine.visual_novel.intent import VN_PROGRESSION_PROMPT
from backend.engine.visual_novel.time import apply_elapsed_time, boundary_elapsed_time
from backend.models.adventure_template import AdventureTemplate
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldExit, WorldScene
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import TurnRoles, final_payload, install_roles, seed_vn


def adventure(**values):
    return SimpleNamespace(
        **dict(rule_enforcement_mode="vn", time_per_turn=5, max_time_per_turn=None, time_config={})
        | values
    )


@pytest.mark.parametrize("cap, expected", [(None, 30), (5, 5), (2, 2), (0, 30)])
def test_confirmed_wait_never_subtracts_an_uncharged_base(cap, expected):
    state = SimpleNamespace(in_game_time=20)
    event = GameEvent(extra_time_minutes=30)
    assert apply_elapsed_time(state, event, adventure(max_time_per_turn=cap))
    assert state.in_game_time == 20 + expected
    assert event.extra_time_minutes == expected


def test_nested_cap_and_nonnegative_bounded_elapsed():
    state = SimpleNamespace(in_game_time=20)
    settings = adventure(time_config={"max_time_per_turn": 3})
    event = GameEvent(extra_time_minutes=30)
    apply_elapsed_time(state, event, settings)
    assert state.in_game_time == 23
    apply_elapsed_time(state, GameEvent(extra_time_minutes=-100), settings)
    assert state.in_game_time == 23
    apply_elapsed_time(state, GameEvent(extra_time_minutes=100000), adventure())
    assert state.in_game_time == 23 + 1440


def test_brief_exchange_has_no_fixed_tick_and_prompt_distinguishes_time_mentions():
    state = SimpleNamespace(in_game_time=20)
    assert not apply_elapsed_time(state, GameEvent(), adventure())
    assert state.in_game_time == 20
    assert "a brief exchange" in VN_PROGRESSION_PROMPT
    assert "sustained" in VN_PROGRESSION_PROMPT
    assert "recounting yesterday, promising to meet tomorrow" in VN_PROGRESSION_PROMPT
    assert "does not itself advance the clock" in VN_PROGRESSION_PROMPT


@pytest.mark.asyncio
@pytest.mark.parametrize("elapsed, override, expected", [(12, None, 12), (0, None, 5), (0, 90, 90)])
async def test_scene_boundary_does_not_double_charge_explicit_elapsed(elapsed, override, expected):
    manager = SimpleNamespace(state=SimpleNamespace(in_game_time=0), adventure=adventure())
    event = GameEvent(extra_time_minutes=elapsed, time_override_minutes=override)
    apply_elapsed_time(manager.state, event, manager.adventure)
    messages = [
        item async for item in advance_in_game_turn(manager, SimpleNamespace(scripts=[]), event)
    ]
    assert not messages
    assert manager.state.in_game_time == expected
    assert boundary_elapsed_time(adventure(max_time_per_turn=2), GameEvent()) == 2


class ClockRoles(TurnRoles):
    def __init__(self, elapsed, destination=None):
        super().__init__()
        self.elapsed, self.destination = elapsed, destination

    async def structured(self, *args, **kwargs):
        result = await super().structured(*args, **kwargs)
        if type(result).__name__.startswith("VNProgressionIntent"):
            result.extra_time_minutes = self.elapsed
            result.new_scene_id = self.destination
        return result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "elapsed, cap, destination, expected",
    [
        (30, None, None, 30),
        (30, 5, None, 5),
        (30, 2, None, 2),
        (12, None, "GARDEN", 12),
        (0, None, None, 0),
    ],
)
async def test_real_vn_clock_persists_and_reaches_streamed_sheet(
    monkeypatch, elapsed, cap, destination, expected
):
    roles = ClockRoles(elapsed, destination)
    install_roles(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _avatar, state, _source_id = await seed_vn(db)
        template = await db.get(AdventureTemplate, "adv-1")
        template.max_time_per_turn = cap
        if destination:
            db.add_all(
                [
                    WorldScene(
                        id=destination,
                        session_id="session-1",
                        label="Garden",
                        description="A quiet garden.",
                    ),
                    WorldExit(
                        session_id="session-1",
                        from_scene_id="START",
                        to_scene_id=destination,
                        label="Garden door",
                        is_locked=False,
                    ),
                ]
            )
        await db.commit()
        manager = GameTurnManager(db, "session-1", user)
        action = "I walk to the garden." if destination else "I wait for a while."
        if destination:
            manager.adventure_gen.classify_short_intent = AsyncMock(
                return_value={
                    "explicit_transition": True,
                    "destination_id": destination,
                    "action_quote": action,
                }
            )
        if elapsed == 0:
            action = "Will we meet tomorrow?"
        chunks = [item async for item in manager.process_turn(action)]
        assert not any(item.startswith("event: error") for item in chunks), "".join(chunks)
        assert final_payload(chunks)["sheet"]["in_game_time"] == expected
        states = [
            json.loads(item.split("data: ", 1)[1])
            for item in chunks
            if item.startswith("event: state")
        ]
        assert states[-1]["sheet"]["in_game_time"] == expected
        await db.refresh(state)
        assert state.in_game_time == expected
        assert state.current_scene_id == (destination or "START")
        expected_clock = MemoryManager.format_game_time(
            expected,
            time_system=state.time_system or template.time_system or "calendar",
            time_config=state.time_config or template.time_config,
        )
        assert f"CURRENT GAME TIME: {expected_clock}" in json.dumps(
            roles.prompts, ensure_ascii=False, default=str
        )
        state_id = state.id
    async with TestSessionLocal() as db:
        assert (await db.get(SessionState, state_id)).in_game_time == expected
