"""Explicit completed skips are distinct from capped estimates and mentioned dates."""

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.engine.narrated_items.schema import ItemExtraction
from backend.engine.physical_conditions.ledger import read
from backend.engine.rule_engine import GameEvent
from backend.engine.visual_novel.intent import VNProgressionIntent
from backend.engine.visual_novel.schema import InteractionPlan
from backend.engine.visual_novel.time import apply_elapsed_time, boundary_elapsed_time
from backend.engine.visual_novel.time_passage import TimePassage, apply
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import TurnRoles, final_payload, install_roles, seed_vn


class PassageRoles(TurnRoles):
    def __init__(self, request="Прошло 3 дня.", *, basis="elapsed", amount=3, unit="days"):
        super().__init__()
        self.passage = {"amount": amount, "unit": unit, "basis": basis, "evidence": request}

    async def structured(self, *args, **kwargs):
        schema = kwargs.get("response_model") or args[2]
        if schema is InteractionPlan:
            self.calls.append((schema.__name__, args, kwargs))
            return InteractionPlan()
        result = await super().structured(*args, **kwargs)
        if schema is not ItemExtraction:
            result.time_passage = self.passage
        return result


def host(**changes):
    return SimpleNamespace(
        state=SimpleNamespace(in_game_time=100, time_system="calendar"),
        adventure=SimpleNamespace(max_time_per_turn=None, time_config={}, **changes),
    )


def test_three_days_use_host_arithmetic_once_and_do_not_add_a_boundary_surcharge():
    manager = host()
    event = GameEvent(extra_time_minutes=120)
    apply(
        manager,
        event,
        {"amount": 3, "unit": "days", "basis": "elapsed", "evidence": "Прошло 3 дня."},
        "Прошло 3 дня.",
    )
    assert manager.state.in_game_time == 100  # Proposal handling does not itself advance time.
    assert event.extra_time_minutes == 0 and event.time_override_minutes == 4420
    assert apply_elapsed_time(manager.state, event, manager.adventure)
    assert manager.state.in_game_time == 4420
    assert boundary_elapsed_time(manager.adventure, event) == 0


@pytest.mark.parametrize(
    "basis,text",
    [
        ("future", "Через три дня встретимся."),
        ("recalled", "Вчера он рассказывал, как прошло три дня."),
        ("uncertain", "А если бы прошло три дня?"),
    ],
)
def test_future_recalled_or_uncertain_passages_do_not_advance_the_current_clock(basis, text):
    manager = host()
    event = GameEvent(extra_time_minutes=30)
    apply(manager, event, {"amount": 3, "unit": "days", "basis": basis, "evidence": text}, text)
    assert event.time_override_minutes is None and event.extra_time_minutes == 0
    assert not apply_elapsed_time(manager.state, event, manager.adventure)
    assert manager.state.in_game_time == 100


@pytest.mark.parametrize(
    "value",
    [
        {"amount": -1},
        {"amount": True},
        {"unit": "months"},
        {"evidence": "Not in this input."},
        {"amount": 366},
    ],
)
def test_invalid_optional_passage_is_rejected_without_aborting_other_intent(value):
    raw = {"amount": 3, "unit": "days", "basis": "elapsed", "evidence": "Прошло 3 дня.", **value}
    parsed = VNProgressionIntent.model_validate(
        {"time_passage": raw, "narrative_description": "Ordinary scene continues."}
    )
    manager, event = host(), GameEvent()
    apply(manager, event, parsed.time_passage, "Прошло 3 дня.")
    assert event.time_override_minutes is None
    assert "not applied" in event.narrative_description


def test_explicit_passage_respects_author_limits_and_cannot_convert_custom_units():
    raw = {"amount": 3, "unit": "days", "basis": "elapsed", "evidence": "Прошло 3 дня."}
    manager = host()
    manager.adventure.max_time_per_turn = 5
    event = GameEvent()
    apply(manager, event, raw, raw["evidence"])
    assert event.time_override_minutes is None and "time limit" in event.narrative_description
    manager.adventure.max_time_per_turn = None
    manager.state.time_system = "units"
    event = GameEvent()
    apply(manager, event, raw, raw["evidence"])
    assert (
        event.time_override_minutes is None and "custom time units" in event.narrative_description
    )
    with pytest.raises(ValidationError):
        TimePassage.model_validate({**raw, "amount": 1000000})


@pytest.mark.asyncio
async def test_three_day_player_declaration_reaches_saved_clock_narration_and_condition_check(
    monkeypatch,
):
    request = "Прошло 3 дня."
    roles = PassageRoles(request)
    install_roles(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _, state, _ = await seed_vn(db)
        events = [
            part async for part in GameTurnManager(db, "session-1", user).process_turn(request)
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
        assert final_payload(events)["sheet"]["in_game_time"] == 4320
        await db.refresh(state)
        assert state.in_game_time == 4320
        assert read(state.entity_states).last_check["minute"] == 4320
        assert read(state.entity_states).last_check["proposed_count"] == 0
        assert "4320" in json.dumps(roles.prompts, ensure_ascii=False, default=str)
        assert len(roles.calls) == 3
