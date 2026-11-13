"""Movement denial traces preserve the existing event and persistence boundaries."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend.engine.gameplay.guardrails import world_rules
from backend.engine.living_world import rules
from backend.engine.living_world.schema import Event
from backend.engine.narrated_movement import runtime
from backend.engine.rule_engine import EntityMovement, GameEvent
from backend.models.world_entity import WorldEntity, WorldScene
from tests.test_narrated_movement_guards import move, pending


@pytest.fixture
def rejection(monkeypatch):
    observer = Mock()
    for module in (runtime, world_rules, rules):
        monkeypatch.setattr(module, "reject", observer, raising=False)
    return observer


@pytest.mark.parametrize(
    "changes",
    [
        {"basis": "intention"},
        {"actor_id": "FOREIGN"},
        {"destination_scene_id": "FAR"},
        {"evidence": "No such departure."},
    ],
)
def test_narrated_movement_rejections_include_proposal_and_source(rejection, changes):
    proposal = move(**changes)
    source = pending([proposal])
    before = deepcopy(source.before)
    event, accepted, errors = runtime._event(source)
    assert errors and not accepted and not event.moved_entities
    assert source.before == before
    rejection.assert_called_once()
    assert rejection.call_args.args[:2] == ("movement", "narrated_movement.invalid_proposal")
    assert rejection.call_args.kwargs["proposal"] == proposal
    assert rejection.call_args.kwargs["source_context"] == before


def test_unconfirmed_movement_completion_records_attempt_without_adopting_it(rejection):
    source = pending(None)
    host = SimpleNamespace(_pending_narrated_movement=source)
    runtime.complete(host, [move()], confirmed=False)
    assert source.proposals is None
    rejection.assert_called_once()
    assert rejection.call_args.args[:2] == ("movement", "narrated_movement.unconfirmed")


@pytest.mark.parametrize("proposals", [[], [move(destination_scene_id="ROOM")]])
def test_no_change_or_confirmed_local_movement_is_not_a_rejection(rejection, proposals):
    _, accepted, errors = runtime._event(pending(proposals))
    assert len(accepted) == len(proposals) and errors == []
    rejection.assert_not_called()


async def test_changed_movement_source_is_traced_and_state_is_preserved(monkeypatch, rejection):
    source = pending([move()])
    state = SimpleNamespace(entity_states={}, current_scene_id="ROOM", session_id="session")
    host = SimpleNamespace(
        state=state,
        db=SimpleNamespace(),
        _pending_narrated_movement=source,
        _save_chat_message=AsyncMock(),
    )
    monkeypatch.setattr(runtime, "session_objects", AsyncMock(return_value=[]))
    monkeypatch.setattr(runtime, "context", AsyncMock(return_value={"changed": True}))
    before = deepcopy(state.entity_states)
    assert await runtime.finish(host, SimpleNamespace(id="reply", content=source.narration))
    assert state.entity_states == before and host._pending_narrated_movement is None
    rejection.assert_called_once()
    assert rejection.call_args.args[:2] == ("movement", "narrated_movement.stale_source")


def _guard(movable=True, allowed=None):
    guard = world_rules.WorldRulesMixin()
    guard.manager = SimpleNamespace(
        state=SimpleNamespace(entity_states={}), game_id="session", turn_language="en"
    )
    npc = WorldEntity(
        id="GUIDE",
        entity_type="NPC",
        name="Keeper",
        description="A keeper.",
        current_scene_id="ROOM",
        moveable=movable,
        movement_type="MOVABLE" if movable else "STATIONARY",
        allowed_scenes=allowed or [],
    )
    return guard, npc


@pytest.mark.parametrize(
    "movable,allowed,code",
    [(False, [], "npc_movement.stationary"), (True, ["ROOM"], "npc_movement.restricted")],
)
def test_rpg_npc_movement_guard_records_exact_refused_move(rejection, movable, allowed, code):
    guard, npc = _guard(movable, allowed)
    proposal = EntityMovement(entity_id="GUIDE", to_scene_id="OTHER")
    assert guard._npc_move_violation(npc, proposal)
    assert proposal.to_scene_id == "OTHER"
    rejection.assert_called_once()
    assert rejection.call_args.args[:2] == ("movement", code)
    assert rejection.call_args.kwargs["proposal"] == proposal


async def test_unknown_rpg_destination_is_traced_before_discarding_proposal(rejection):
    guard, npc = _guard()
    guard._session_entities = AsyncMock(return_value=[npc])
    guard.manager.db = SimpleNamespace(
        scalars=AsyncMock(
            return_value=[WorldScene(id="ROOM", label="Archive", description="Quiet.")]
        )
    )
    event = GameEvent(moved_entities=[EntityMovement(entity_id="GUIDE", to_scene_id="MISSING")])
    assert await guard._enforce_npc_movement_guardrails(event)
    assert event.moved_entities == []
    rejection.assert_called_once()
    assert rejection.call_args.args[:2] == ("movement", "npc_movement.unknown_destination")


def test_living_world_cancellation_is_traced_without_extra_state_changes(rejection):
    event = Event(event_id="move", due=5, kind="MOVE", actor="GUIDE", destination="FAR")
    before = event.model_dump()
    rules.cancel(event, "Movement is not permitted by the current world state.")
    assert event.status == "CANCELLED"
    assert event.model_dump() == {
        **before,
        "status": "CANCELLED",
        "result": "Movement is not permitted by the current world state.",
    }
    rejection.assert_called_once()
    assert rejection.call_args.args[:2] == ("movement", "living_world.cancelled")
