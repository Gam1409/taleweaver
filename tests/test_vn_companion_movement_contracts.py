"""Confirmed player travel preserves companion choices without replacing NPC control."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.text_evidence import EvidenceSpan
from backend.engine.chpm.kernel import digest
from backend.engine.chpm.recovery_contracts import RecoveryAudit
from backend.engine.chpm.schema import KernelState, Settings
from backend.engine.chpm.state import KEY
from backend.engine.gameplay.movement_intent import PlayerTraversal
from backend.engine.mutation_targets import TargetIndex
from backend.engine.narrated_movement.outcomes import MovementOutcome
from backend.engine.rule_engine import EntityMovement, GameEvent, WorldEntityUpdate
from backend.engine.visual_novel.movement_contracts import VnMovement
from backend.engine.visual_novel.movement_recovery import _resolve_actor
from backend.engine.visual_novel.movement_sources import _source


def setup(mode):
    request = SimpleNamespace(
        id="input",
        session_id="session",
        revision_id="revision",
        role="user",
        content="Let us go to the annex now.",
        scene_id="START",
        is_debug=False,
        npc_journal=None,
    )
    travel = PlayerTraversal(
        message_id=request.id,
        origin="START",
        destination="ANNEX",
        source=request.content,
        companions=frozenset({"LINA"}),
    )
    manager = SimpleNamespace(
        game_id="session",
        db=SimpleNamespace(get=AsyncMock(return_value=request)),
        state=SimpleNamespace(
            entity_states={
                KEY: KernelState(settings=Settings(mode=mode, actor_ids=["LINA"])).model_dump()
            }
        ),
        _vn_story_beat=None,
        _vn_player_message_id=request.id,
        _vn_movement_input=request.id,
        _vn_movement_sources={"current_player_action": _source(request, "player")},
        _confirmed_player_travel=travel,
    )
    event = GameEvent(
        new_scene_id="ANNEX",
        moved_entities=[EntityMovement(entity_id="LINA", to_scene_id="ANNEX")],
    )
    before = {
        "scene_id": "START",
        "actors": {"LINA": {"can_move": True, "allowed_destinations": ["ANNEX"]}},
    }
    return manager, event, before, request


async def check(manager, event, before):
    await _resolve_actor(
        manager,
        event,
        "LINA",
        event.moved_entities,
        event.updated_entities or [],
        (event.moved_entities, event.updated_entities or []),
        before,
        TargetIndex([{"id": "ANNEX"}]),
        1,
    )


@pytest.mark.parametrize("mode", ["off", "shadow", "live"])
async def test_companions_retain_their_actual_controller(mode):
    manager, event, before, _ = setup(mode)
    if mode == "live":
        with pytest.raises(ValueError, match="source"):
            await check(manager, event, before)
        return
    await check(manager, event, before)
    assert event.moved_entities[0].entity_id == "LINA"
    assert event.moved_entities[0].to_scene_id == event.new_scene_id == "ANNEX"


@pytest.mark.parametrize(
    "changed",
    ["missing_confirmation", "unproposed", "input", "origin", "destination", "text", "revision"],
)
async def test_companion_admission_requires_unchanged_current_confirmation(changed):
    manager, event, before, request = setup("off")
    travel = manager._confirmed_player_travel
    if changed == "missing_confirmation":
        manager._confirmed_player_travel = None
    elif changed == "unproposed":
        manager._confirmed_player_travel = replace(travel, companions=frozenset())
    elif changed == "input":
        manager._vn_player_message_id = "other-input"
    elif changed == "origin":
        before["scene_id"] = "ELSEWHERE"
    elif changed == "destination":
        event.new_scene_id = "ELSEWHERE"
    elif changed == "text":
        request.content = "I remain here."
    elif changed == "revision":
        request.revision_id = "edited"
    with pytest.raises(ValueError):
        await check(manager, event, before)


@pytest.mark.parametrize("gate", ["stationary", "route", "unavailable", "conflicting_presence"])
async def test_confirmed_shared_travel_cannot_bypass_movement_owners(gate):
    manager, event, before, _ = setup("off")
    actor = before["actors"]["LINA"]
    if gate == "stationary":
        actor["can_move"] = False
    elif gate == "route":
        actor["allowed_destinations"] = []
    elif gate == "unavailable":
        before["actors"] = {}
    elif gate == "conflicting_presence":
        event.updated_entities = [WorldEntityUpdate(entity_id="LINA", presence="audible")]
    with pytest.raises(ValueError):
        await check(manager, event, before)


@pytest.mark.parametrize(
    "proof",
    [
        {"kind": "previous_narration", "passage_id": "history:p0", "basis": "completed"},
        {"kind": "previous_narration", "passage_id": "history:p0", "basis": "uncertain"},
        {"kind": "invalid", "passage_id": "history:p0", "basis": "completed"},
        None,
    ],
)
async def test_explicit_source_cannot_be_reinterpreted_as_a_fresh_companion_choice(proof):
    manager, event, before, _ = setup("off")
    proposal = VnMovement.model_validate(
        {"entity_id": "LINA", "to_scene_id": "ANNEX", "movement_source": proof}
    )
    event.moved_entities = [proposal]
    with pytest.raises(ValueError):
        await check(manager, event, before)


async def test_blocked_history_stays_blocked_during_a_confirmed_current_shared_transition():
    manager, event, before, request = setup("off")
    text = "Lina walks through the door into the annex."
    previous = SimpleNamespace(
        **{
            **vars(request),
            "id": "previous",
            "role": "assistant",
            "content": text,
        }
    )
    outcome = MovementOutcome(
        actor_id="LINA",
        status="blocked",
        evidence=text,
        evidence_span=EvidenceSpan(start=0, end=len(text)),
    )
    previous.npc_recovery = RecoveryAudit(
        content_hash=digest(text),
        revision_id=previous.revision_id,
        scene_id="START",
        actors={"LINA": 0},
        movement_outcomes=(outcome,),
    ).model_dump()
    manager._vn_movement_sources["previous_narration"] = _source(previous, "history", (outcome,))
    manager.db.get = AsyncMock(
        side_effect=lambda _model, key, **_kwargs: {request.id: request, previous.id: previous}[key]
    )
    event.moved_entities = [
        VnMovement(
            entity_id="LINA",
            to_scene_id="ANNEX",
            movement_source={
                "kind": "previous_narration",
                "passage_id": "history:p0",
                "basis": "completed",
            },
        )
    ]
    with pytest.raises(ValueError, match="previously blocked"):
        await check(manager, event, before)
