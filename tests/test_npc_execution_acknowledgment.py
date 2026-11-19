"""Private next-turn feedback distinguishes deliberate no action from rejected execution."""

import json

import pytest
from pydantic import ValidationError

from backend.engine.chpm import lifecycle
from backend.engine.chpm.state import KEY, load, retract
from backend.engine.chpm.two_phase_execution import _selected_references
from backend.engine.npc_actions import acknowledgment
from backend.engine.npc_actions.acknowledgment_contracts import (
    PublicationAcknowledgment,
    SelectedActionExecution,
)
from backend.engine.npc_actions.contracts import Approach, ChangeState, Give, Move, Take
from backend.engine.turn_replay.snapshot import capture, restore
from backend.engine.visual_novel.continuity import SCENE
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.test_chpm_host_turn import run
from tests.test_chpm_local_failure_turn import install
from tests.test_npc_action_previews import fixture as preview_fixture
from tests.test_npc_publication_acknowledgment import next_input
from tests.test_npc_two_phase_turn import (
    CUP,
    PLAYER,
    TAKE,
    CupRoles,
    assert_committed,
    reload,
    seed,
)


class RejectedExecutionRoles(CupRoles):
    def __init__(self):
        super().__init__([TAKE])
        self.next_turn = False

    def answer(self, payload, functions, phase, kwargs):
        if phase != "npc_execution":
            self.steps = [TAKE] if not self.next_turn and payload["actor_id"] == "LINA" else []
        result = super().answer(payload, functions, phase, kwargs)
        if phase == "npc_execution":
            return [
                (name, {**arguments, "item_id": "UNSELECTED_ITEM"}) for name, arguments in result
            ]
        return result


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_rejected_selection_and_deliberate_no_action_survive_reload_in_own_context(
    monkeypatch, protocol
):
    roles = RejectedExecutionRoles()
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await seed(db, protocol, pair=True)
        user_id, session_id = user.id, state.session_id
        first, events = await run(db, user, PLAYER)
        assert_committed(events)
        saved = load(first.state)
        assert saved.actors["LINA"].agent_audit[-1]["status"] == "rejected"
        assert saved.actors["LINA"].last_publication.operations == ()

    async with TestSessionLocal() as db:
        user, manager, snapshot = await reload(db, session_id, user_id)
        assert snapshot.owners[CUP] == SCENE
        saved = load(manager.state)
        rejected = saved.actors["LINA"].last_publication.execution
        waiting = saved.actors["MILA"].last_publication.execution
        assert rejected.status == "rejected" and waiting.status == "not_attempted"
        assert [step.model_dump(exclude_none=True) for step in rejected.steps] == [TAKE]
        assert {error.code for error in rejected.gate_errors} == {"goal_operation_mismatch"}
        assert waiting.steps == waiting.gate_errors == ()
        roles.next_turn = True
        _, events = await run(db, user, "I wait for each of you to speak.")
        assert_committed(events)
        supplied = {
            payload["actor_id"]: payload["previous_action_results_not_current_state"]
            for payload, _ in roles.choices[2:]
        }
        assert supplied["LINA"]["operations"] == supplied["MILA"]["operations"] == []
        assert supplied["LINA"]["execution"]["status"] == "rejected"
        assert supplied["MILA"]["execution"]["status"] == "not_attempted"
        assert "goal_operation_mismatch" not in json.dumps(supplied["MILA"])
        assert "UNSELECTED_ITEM" not in json.dumps(supplied)
        assert all(
            "previous_action_results_not_current_state" not in json.dumps(payload)
            and "goal_operation_mismatch" not in json.dumps(payload)
            for payload in roles.reviews
        )
        assert len(roles.executions) == 2


def test_legacy_acknowledgment_keeps_its_saved_shape_and_unknown_execution():
    raw = {"attempt_id": "prior-attempt", "operations": []}
    value = PublicationAcknowledgment.model_validate(raw)
    assert value.execution is None and value.model_dump(mode="json") == raw


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "not_attempted"},
        {"status": "rejected", "steps": []},
        {"status": "rejected", "gate_errors": []},
        {"steps": [TAKE] * 3},
        {"gate_errors": [{"code": "goal_operation_mismatch"}] * 3},
        {"gate_errors": [{"code": "Arbitrary private provider diagnostics"}]},
        {"gate_errors": [{"code": "goal_operation_mismatch", "message": "Private detail"}]},
        {"steps": [{**TAKE, "action": "A private plan description."}]},
        {"steps": [{**TAKE, "dimension": "A private or unsupported dimension"}]},
        {"steps": [{**TAKE, "position": "A private position description"}]},
        {"steps": [{**TAKE, "recipient_id": "ANOTHER_ACTOR"}]},
        {"effect": {"item_id": CUP}},
        {"operation_id": "invented-receipt"},
    ],
)
def test_execution_feedback_rejects_unbounded_untyped_or_fictitious_dispositions(changes):
    raw = {
        "status": "rejected",
        "steps": [TAKE],
        "gate_errors": [{"code": "goal_operation_mismatch", "path": "/steps/0/item_id"}],
    }
    with pytest.raises(ValidationError):
        SelectedActionExecution.model_validate({**raw, **changes})


@pytest.mark.parametrize(
    "step, expected",
    [
        (Take(tool="take_item", item_id="HIDDEN"), {"tool": "take_item"}),
        (Take(tool="take_item", item_id="npc"), {"tool": "take_item"}),
        (
            Give(tool="give_item", item_id="KEY", recipient_id="UNKNOWN"),
            {"tool": "give_item", "item_id": "KEY"},
        ),
        (Approach(tool="approach", target_id="UNKNOWN"), {"tool": "approach"}),
        (Move(tool="move_to", destination_scene_id="UNKNOWN"), {"tool": "move_to"}),
        (
            ChangeState(
                tool="change_item_state",
                item_id="KEY",
                dimension="unregistered",
                detail="Private detail",
            ),
            {"tool": "change_item_state", "item_id": "KEY"},
        ),
    ],
)
def test_execution_feedback_keeps_only_captured_observer_references(step, expected):
    _, scope, _ = preview_fixture()
    assert _selected_references(scope, step).model_dump(exclude_none=True) == expected


@pytest.mark.parametrize("source", ["input", "reply"])
async def test_failed_execution_feedback_retains_existing_source_freshness(monkeypatch, source):
    roles = RejectedExecutionRoles()
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _ = await seed(db, "json", pair=False)
        manager, events = await run(db, user, PLAYER)
        assert_committed(events)
        previous = load(manager.state).actors["LINA"]
        upcoming = await next_input(manager, db)
        supplied = await acknowledgment.context(manager, previous, upcoming, "LINA")
        assert supplied["execution"]["status"] == "rejected"
        identifier = previous.observation.message_id if source == "input" else previous.reply_id
        row = await db.get(ChatMessage, identifier)
        row.content = "The prior saved source was changed."
        await db.flush()
        assert await acknowledgment.context(manager, previous, upcoming, "LINA") is None


async def test_failed_execution_feedback_follows_retraction_fork_and_snapshot_restore(monkeypatch):
    roles = RejectedExecutionRoles()
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _ = await seed(db, "json", pair=False)
        manager, events = await run(db, user, PLAYER)
        assert_committed(events)
        previous = load(manager.state).actors["LINA"]
        saved = await capture(db, manager.game_id)
        copied = lifecycle.fork(
            manager.state.entity_states,
            {previous.observation.message_id: "copy-input", previous.reply_id: "copy-reply"},
            "copy-session",
        )
        assert not copied[KEY]["actors"]
        retract(manager.state, previous.reply_id)
        assert not load(manager.state).actors
        await db.commit()
        await restore(db, manager.game_id, saved)
        await db.commit()
        await db.refresh(manager.state)
        await db.refresh(manager.avatar)
        restored = load(manager.state).actors["LINA"]
        assert restored.last_publication == previous.last_publication
        supplied = await acknowledgment.context(
            manager, restored, await next_input(manager, db), "LINA"
        )
        assert supplied["execution"]["status"] == "rejected" and supplied["operations"] == []
