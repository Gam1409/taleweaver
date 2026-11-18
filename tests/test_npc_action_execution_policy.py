"""All prose consumers share current command authority, independently of tool transport."""

import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.engine.chpm import (
    continuation,
    inference,
    narration_repair_input,
    passages,
    prompts,
    receipt_review,
    rendering,
    runtime,
)
from backend.engine.chpm.errors import RecoverableChpmError
from backend.engine.chpm.state import KEY, load
from backend.engine.npc_actions import instructions
from tests.conftest import TestSessionLocal
from tests.test_chpm_action_turn import ActionRoles
from tests.test_chpm_host_turn import run
from tests.test_chpm_notebook_turn import ACTION, install
from tests.test_chpm_observable_turn import prepare
from tests.test_npc_command_resolution_handoff import RESOLUTION, TEXT, command_turn
from tests.test_vn_turn_integration import NARRATION

UNCONTROLLED_PERMISSIONS = (
    "Wording, tone and compatible expressive or practical actions remain free.",
    "Literal wording is unnecessary; style and compatible expressive or practical actions are free.",
    "selected intention is allowed without a separate player command or approval.",
    "from world-pass hints; wording and compatible own actions remain free.",
)


class ExecutionRoles(ActionRoles):
    def __init__(self, *, repair=False):
        super().__init__()
        self.repair = repair
        self.reviews, self.repairs = [], []

    async def simple(self, system, payload, model, **kwargs):
        phase = kwargs.get("phase")
        if phase == "validation":
            self.reviews.append((system, json.loads(payload)))
            if self.repair and len(self.reviews) == 1:
                self.chpm_calls.append(phase)
                return json.dumps(
                    {
                        "review_scope": self.reviews[-1][1]["review_scope"],
                        "matches": False,
                        "rejections": [{"reason_code": "world", "actor_id": "LINA"}],
                    }
                )
        if phase == "repair":
            self.repairs.append((system, json.loads(payload)))
        return await super().simple(system, payload, model, **kwargs)


@pytest.mark.parametrize("protocol", ["native", "json"])
@pytest.mark.parametrize("repair", [False, True])
async def test_nonempty_published_commands_share_execution_authority_through_real_turn(
    monkeypatch, protocol, repair
):
    roles = ExecutionRoles(repair=repair)
    install(monkeypatch, roles)
    admissions = []
    reserve = inference.reserve

    def reserved(settings, usage, size):
        admissions.append(size)
        reserve(settings, usage, size)

    monkeypatch.setattr(inference, "reserve", reserved)
    async with TestSessionLocal() as db:
        user, state = await prepare(db, "integrated", protocol, False)
        kernel = load(state)
        kernel.settings.action_tools = True
        state.entity_states = {**state.entity_states, KEY: kernel.model_dump()}
        await db.commit()

        manager, events = await run(db, user, ACTION)

        assert any(event.startswith("event: final") for event in events), "".join(events)
        assert not any(event.startswith("event: error") for event in events)
        narration = "\n".join(
            message["content"]
            for _args, options in roles.prompts
            for message in options["messages"]
        )
        assert instructions.EXECUTION in narration
        assert all(permission not in narration for permission in UNCONTROLLED_PERMISSIONS)
        for system, body in roles.reviews:
            assert instructions.EXECUTION in system
            assert all(permission not in system for permission in UNCONTROLLED_PERMISSIONS)
            outcomes = body["contract"]["LINA"]["authoritative_command_outcomes"]
            assert [row["status"] for row in outcomes] == ["applied", "applied"]
            assert [row["tool"] for row in outcomes] == ["change_item_state", "put_down_item"]
        assert len(roles.repairs) == int(repair)
        for system, _body in roles.repairs:
            assert instructions.EXECUTION in system
            assert all(permission not in system for permission in UNCONTROLLED_PERMISSIONS)
        saved = load(manager.state)
        assert saved.usage.calls == (6 if repair else 4)
        assert saved.usage.input_chars == sum(admissions)
        assert all(size <= saved.settings.max_input_chars for size in admissions)


@pytest.mark.parametrize(
    "status", ["applied", "attempted", "blocked", "stale", "skipped_dependency"]
)
@pytest.mark.parametrize("empty_actor", [False, True])
def test_complete_execution_policy_is_identical_for_all_published_statuses(status, empty_actor):
    outcomes = {"npc": [{"index": 0, "tool": "give_item", "status": status}]}
    if status == "applied":
        outcomes["npc"][0]["effect"] = {"item_id": "KEY", "destination_owner": "__player__"}
    if empty_actor:
        outcomes["other"] = []
    before = deepcopy(outcomes)
    narration = instructions.for_outcomes(outcomes)
    review = instructions.resolution_instructions(outcomes)
    assert narration == review
    assert instructions.EXECUTION in narration
    assert instructions.RESOLUTION_CHRONOLOGY in narration
    assert "Blocked/stale/skipped" in narration
    assert "independent" in narration and "player" in narration
    assert outcomes == before


def test_continuation_preserves_complete_execution_policy_after_abandoning_decisions():
    current = command_turn()
    continuation.activate(current, "review_unavailable")
    assert instructions.EXECUTION in continuation.contract(current)
    assert not current.decisions


def test_absent_control_retains_original_narration_review_and_repair_policies():
    current = command_turn({})
    assert prompts.NARRATE in runtime.contract(current)
    assert instructions.for_outcomes({}) == instructions.resolution_instructions({}) == ""
    system, _ = narration_repair_input.build(
        current, "Original policy", NARRATION, RESOLUTION, [], portrait_reminder=""
    )
    assert narration_repair_input.CONTRACT_RULES in system
    assert instructions.EXECUTION not in system


@pytest.mark.parametrize("overflow", [0, 1])
async def test_actual_review_counts_complete_policy_at_exact_unchanged_input_limit(
    monkeypatch, overflow
):
    current = command_turn()
    host = current._control_host
    composed = []
    compose = inference.compose

    def record(instruction, payload, schema, identifiers):
        result = compose(instruction, payload, schema, identifiers)
        composed.append((instruction, payload, result))
        return result

    async def response(_system, payload, _model, **_kwargs):
        body = json.loads(payload)
        return json.dumps(
            {
                "review_scope": body["review_scope"],
                "matches": True,
                "completed_changes": [],
                "evidence": [{"actor_id": "npc", "passage_id": next(iter(body["passages"]))}],
            }
        )

    model = SimpleNamespace(
        model="mock",
        max_tokens=8192,
        request_timeout=10,
        aexecute_simple_task=AsyncMock(side_effect=response),
    )
    monkeypatch.setattr(inference, "compose", record)
    monkeypatch.setattr(inference, "model_for", lambda *_args: model)
    room = rendering._review_room(current)
    assert instructions.EXECUTION in composed[-1][0]
    assert room == 24000 - sum(map(len, composed[-1][2]))
    # Resolution padding tests the actual serialized request, not a guessed policy allowance.
    body = rendering._review_payload(current, passages.index(TEXT), "")
    baseline = compose(
        composed[-1][0],
        body,
        receipt_review.schema(current),
        rendering._review_identifiers(current, passages.index(TEXT), scope=body["review_scope"]),
    )
    resolution = "x" * (24000 - sum(map(len, baseline)) + overflow)
    if overflow:
        with pytest.raises(RecoverableChpmError, match="24001 > 24000"):
            await rendering._review(host, current, TEXT, resolution)
        model.aexecute_simple_task.assert_not_awaited()
        assert current.usage.calls == 0
    else:
        verdict = await rendering._review(host, current, TEXT, resolution)
        assert verdict.matches
        model.aexecute_simple_task.assert_awaited_once()
        assert current.usage.calls == 1 and current.usage.input_chars == 24000
        assert model.aexecute_simple_task.await_args.args[:2] == composed[-1][2]
    assert current.initial.settings.max_input_chars == 24000
