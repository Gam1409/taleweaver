"""A chosen physical step and a provider call must match before the ordinary draft can stage it."""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from backend.engine.chpm import inference, tool_operations, two_phase_execution
from backend.engine.chpm.errors import InferenceUnavailableError, StaleControlError
from backend.engine.chpm.schema import Settings, Usage
from backend.engine.npc_actions.contracts import Adjust, Give, Take
from tests.observable_state_support import tools_for, world
from tests.test_chpm_native_notebook_loop import call, turn
from tests.test_npc_action_previews import fixture

TAKE = Take(tool="take_item", item_id="KEY")
GIVE = Give(tool="give_item", item_id="KEY", recipient_id="other")


def invocation(identifier, step, **changes):
    return call(identifier, step.tool, step.model_dump(exclude={"tool"}) | changes)


def case(monkeypatch, *replies, used=0, cap=12, prior_repairs=0, seen=()):
    manager, _, draft = fixture()
    tools = tools_for(*world())
    tools.actions = draft
    settings = Settings(mode="live", actor_ids=["npc"], max_calls_per_turn=cap)
    usage = Usage(calls=used, proposal_repairs=prior_repairs)
    seen = set(seen)
    queries = []
    captured = tool_operations.capture(manager, tools)

    async def request(_manager, _settings, _usage, messages, offered, **kwargs):
        assert kwargs["require_tools"] is True and kwargs["phase"] == "npc_execution"
        queries.append((deepcopy(messages), [row["function"]["name"] for row in offered]))
        usage.calls += 1
        reply = replies[len(queries) - 1]
        if isinstance(reply, BaseException):
            raise reply
        return reply() if callable(reply) else reply

    monkeypatch.setattr(inference, "tool_request", request)

    async def execute(*steps):
        return (
            await two_phase_execution.execute(
                manager,
                settings,
                usage,
                tools,
                SimpleNamespace(protocol="native"),
                captured,
                seen,
                steps,
            )
        )[0]

    return execute, draft, usage, queries, seen, manager


async def test_two_phase_exact_ordered_batch_is_atomic_and_uses_real_call_ids(monkeypatch):
    execute, draft, _, queries, seen, _ = case(
        monkeypatch, turn(invocation("c1", TAKE), invocation("c2", GIVE))
    )
    report = await execute(TAKE, GIVE)
    assert report["status"] == "staged" and report["repaired"] is False
    assert draft.approved and draft.requests == [TAKE, GIVE]
    assert [op.tool_call_id for op in draft.operations] == ["c1", "c2"]
    assert len({op.operation_id for op in draft.operations}) == 2
    assert {op.operation_id for op in draft.operations} == {
        r["operation_id"] for r in report["requests"]
    }
    assert seen == {"c1", "c2"} and set(queries[0][1]) == {"take_item", "give_item"}
    assert draft.scope.possessions.owners["KEY"] == "__scene__"
    assert draft.working_copy()[1].owners["KEY"] == "other"


async def test_two_phase_empty_never_calls_the_model(monkeypatch):
    execute, draft, _, queries, _, _ = case(monkeypatch)
    report = await execute()
    assert draft.approved and not draft.requests and not queries
    assert report["status"] == "not_attempted"


@pytest.mark.parametrize(
    "first,code",
    [
        (turn(), "declared_action_without_operation"),
        (turn(invocation("wrong", TAKE, item_id="OTHER_ITEM")), "goal_operation_mismatch"),
        (turn(invocation("wrong", GIVE)), "goal_operation_mismatch"),
        (turn(call("wrong", "inspect_scene", {})), "goal_operation_mismatch"),
        (
            turn(call("wrong", "take_item", {"item_id": "KEY", "actor_id": "other"})),
            "invalid_arguments",
        ),
        (turn(invocation("prior", TAKE)), "invalid_call_envelope"),
    ],
)
async def test_single_correction_uses_original_plan(monkeypatch, first, code):
    execute, draft, usage, queries, _, _ = case(
        monkeypatch, first, turn(invocation("new", TAKE)), seen={"prior"}
    )
    report = await execute(TAKE)
    assert report["status"] == "staged" and report["repaired"] and usage.proposal_repairs == 1
    assert draft.requests == [TAKE] and draft.operations[0].tool_call_id == "new"
    assert code in str(queries[1][0])


async def test_reusing_rejected_call_id_and_owner_failure_cannot_publish_partial_prefix(
    monkeypatch,
):
    execute, draft, usage, _, _, _ = case(
        monkeypatch, turn(invocation("a", TAKE)), turn(invocation("a", TAKE), invocation("b", GIVE))
    )
    report = await execute(TAKE, GIVE)
    assert report["status"] == "rejected" and report["error_type"] == "invalid_call_envelope"
    assert usage.proposal_repairs == 1 and draft.approved and not draft.requests

    bad_give = Give(tool="give_item", item_id="KEY", recipient_id="missing")
    execute, draft, usage, _, _, _ = case(
        monkeypatch, turn(invocation("a", TAKE), invocation("b", bad_give))
    )
    report = await execute(TAKE, bad_give)
    assert report["status"] == "rejected" and usage.calls == 1
    assert draft.approved and not draft.requests and not draft.operations
    assert draft.working_copy()[1].owners["KEY"] == "__scene__"


@pytest.mark.parametrize("kw", [{"prior_repairs": 1}, {"used": 5, "cap": 9}])
async def test_shared_repair_budget_respects_remaining_review_reserve(monkeypatch, kw):
    execute, draft, _, queries, _, _ = case(monkeypatch, turn(), **kw)
    report = await execute(TAKE)
    assert len(queries) == 1 and not report["repaired"]
    assert report["status"] == "rejected" and draft.approved and not draft.operations


async def test_stale_reply_cannot_approve_even_an_empty_replacement(monkeypatch):
    def stale():
        manager._vn_player_message_id = "changed"
        return turn()

    execute, draft, _, queries, _, manager = case(monkeypatch, stale)
    with pytest.raises(StaleControlError):
        await execute(TAKE)
    assert len(queries) == 1 and not draft.approved and not draft.requests


async def test_forged_empty_draft_scope_and_transport_failure_cannot_authorize_actions(monkeypatch):
    execute, draft, _, _, _, _ = case(monkeypatch)
    draft.scope = replace(draft.scope, control={**draft.scope.control, "attempt_id": "foreign"})
    with pytest.raises(StaleControlError):
        await execute()
    assert not draft.approved

    execute, draft, _, queries, _, _ = case(monkeypatch, InferenceUnavailableError("no response"))
    with pytest.raises(InferenceUnavailableError):
        await execute(TAKE)
    assert len(queries) == 1 and not draft.approved


async def test_retry_cannot_reuse_fresh_id_from_partly_invalid_batch(monkeypatch):
    execute, draft, _, _, seen, _ = case(
        monkeypatch,
        turn(invocation("old", TAKE), invocation("discarded", GIVE)),
        turn(invocation("new", TAKE), invocation("discarded", GIVE)),
        seen={"old"},
    )
    report = await execute(TAKE, GIVE)
    assert report["error_type"] == "invalid_call_envelope" and "discarded" in seen
    assert not draft.requests and draft.approved


async def test_replay_and_scene_switch_cannot_claim_existing_draft(monkeypatch):
    execute, draft, _, queries, _, manager = case(monkeypatch, turn(invocation("a", TAKE)))
    await execute(TAKE)
    with pytest.raises(StaleControlError):
        await execute()
    assert len(queries) == 1 and draft.requests == [TAKE]

    def change_scene():
        manager.state.current_scene_id = "PORCH"
        return turn(invocation("b", TAKE))

    execute, draft, _, queries, _, manager = case(monkeypatch, change_scene)
    with pytest.raises(StaleControlError):
        await execute(TAKE)
    assert len(queries) == 1 and not draft.approved and not draft.requests


def test_clothing_region_order_is_not_an_operand_change():
    chosen = Adjust(tool="adjust_clothing", item_id="COAT", uncovered_regions=["torso", "arms"])
    reordered = chosen.model_copy(
        update={"uncovered_regions": list(reversed(chosen.uncovered_regions))}
    )
    assert two_phase_execution._mismatch(chosen, reordered, 0) is None
    altered = chosen.model_copy(update={"uncovered_regions": []})
    assert two_phase_execution._mismatch(chosen, altered, 0) == "/steps/0/uncovered_regions"


async def test_unknown_function_rejection_keeps_provider_ids_consumed(monkeypatch):
    invalid = inference.ToolEnvelopeError(
        "Invalid function", code="unavailable_function", call_ids=("spent",)
    )
    execute, draft, _, _, _, _ = case(monkeypatch, invalid, turn(invocation("spent", TAKE)))
    report = await execute(TAKE)
    assert [row["code"] for row in report["gate_errors"]] == [
        "goal_operation_mismatch",
        "invalid_call_envelope",
    ]
    assert draft.approved and not draft.requests
