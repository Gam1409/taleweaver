"""Controlled proposal generation and its existing correction share execution ownership."""

import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.engine.chpm import cognition, inference, prompts
from backend.engine.chpm.errors import RecoverableChpmError
from backend.engine.chpm.schema import Settings, Usage
from tests.chpm_reference_fixture import response as reference_response
from tests.chpm_repair_fixture import corrections
from tests.observable_state_support import tools_for, world
from tests.test_chpm_action_submission_contract import proposal
from tests.test_chpm_native_notebook_loop import NativeModel, call, turn
from tests.test_npc_action_previews import fixture as action_fixture

LEGACY_EXECUTION = "The narrator realizes speech, feasible own acts or both."
CONTROLLED_EXECUTION = "A proposal or correction cannot execute an action"
LEGACY_PROPOSAL_HASH = "b392e98463e09ea0760f9ce2f5d132d590cb4eac671a9184c6fd18e76eabd599"


class ProposalModel(NativeModel):
    def __init__(self, batches):
        super().__init__(
            [
                turn(
                    *(
                        call(f"round-{index}-{position}", name, arguments)
                        for position, (name, arguments) in enumerate(batch)
                    )
                )
                for index, batch in enumerate(batches)
            ]
        )
        self.portable = []

    async def aexecute_simple_task(self, system, content, _model, **kwargs):
        body = json.loads(content)
        self.portable.append((kwargs["phase"], system, body))
        if kwargs["phase"] == "proposal_repair":
            return corrections(("/choice/reason", "Continue my established purpose."))
        assert kwargs["phase"] == "integrated_decision"
        response = next(self.responses)
        raw = json.dumps(
            {
                "requests": [
                    {"name": request.name, "arguments": json.loads(request.arguments_raw)}
                    for request in response.calls
                ]
            }
        )
        return reference_response(raw, body)

    def initial_requests(self, protocol):
        if protocol == "json":
            return [
                (system, body)
                for phase, system, body in self.portable
                if phase == "integrated_decision"
            ]
        return [
            (messages[0]["content"], json.loads(messages[1]["content"]))
            for messages, _tools, _options in self.requests
        ]


async def deliberate(
    protocol, plan, *, repair=True, actions=True, input_limit=34500, detail="full"
):
    chosen = proposal()
    if detail == "compact":
        del chosen["candidates"]["DEFER"]
    chosen["candidates"]["CONTINUE"]["intention"] = "Offer to inspect the workshop later."
    if repair:
        chosen["choice"]["reason"] = "x" * 301
    batches = [[("inspect_self", {})]]
    if plan in {"staged", "discarded"}:
        batches = [[("take_item", {"item_id": "KEY"})]]
    if plan == "discarded":
        batches.append([("discard_actions", {})])
    batches.append([("submit_decision", chosen)])
    model = ProposalModel(batches)
    manager, scope, draft = action_fixture()
    tools = tools_for(*world())
    manager._chpm_turn = SimpleNamespace(
        input_id=tools.observation.message_id,
        names={"npc": "NPC"},
        decisions={},
        observable_views={"npc": tools.observable},
        action_drafts={"npc": draft} if actions else {},
    )
    manager._chpm_model_factory = lambda _role: model
    usage = Usage()
    settings = Settings(
        mode="live",
        decision_detail=detail,
        actor_ids=["npc"],
        workflow="integrated",
        tool_protocol=protocol,
        action_tools=actions,
        agent_steps=3,
        max_input_chars=input_limit,
    )
    before = deepcopy(scope.states), deepcopy(scope.possessions)
    decision, _ = await cognition.deliberate(
        manager,
        settings,
        usage,
        "npc",
        tools.observation,
        {"authored_goal": "Keep bridges safe"},
        [],
        tools.mind,
    )
    assert (scope.states, scope.possessions) == before
    return model, draft, decision, usage, settings


@pytest.mark.parametrize("protocol", ["native", "json"])
@pytest.mark.parametrize("plan", ["empty", "staged", "discarded"])
async def test_production_initial_and_existing_repair_share_controlled_policy_and_pending_ids(
    protocol, plan
):
    model, draft, decision, usage, settings = await deliberate(protocol, plan)
    initial = model.initial_requests(protocol)
    repairs = [
        (system, body) for phase, system, body in model.portable if phase == "proposal_repair"
    ]

    assert all(LEGACY_EXECUTION not in system for system, _body in initial + repairs)
    assert all(CONTROLLED_EXECUTION in system for system, _body in initial + repairs)
    assert len(repairs) == 1 and usage.proposal_repairs == 1
    assert usage.calls == len(initial) + 1
    original = initial[-1][1]
    repaired = repairs[0][1]
    expected = draft.context()
    assert original["pending_actions_not_world_facts"] == expected
    assert repaired["pending_actions_not_world_facts"] == expected
    assert repaired["agent_lookup_status"] == original["agent_lookup_status"]
    assert expected["status"] == "pending_not_world_facts"
    assert expected["count"] == (1 if plan == "staged" else 0)
    assert expected["operation_ids"] == [operation.operation_id for operation in draft.operations]
    assert draft.approved and draft.published_results is None
    assert decision.selected.intention == "Offer to inspect the workshop later."
    assert len(decision.proposal.candidates) == 2
    assert settings.agent_steps == 3 and settings.max_input_chars == 34500


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_memory_only_proposal_and_repair_retain_legacy_execution_policy(protocol):
    model, draft, _decision, usage, _settings = await deliberate(protocol, "empty", actions=False)
    initial = model.initial_requests(protocol)
    repairs = [
        (system, body) for phase, system, body in model.portable if phase == "proposal_repair"
    ]
    assert all(LEGACY_EXECUTION in system for system, _body in initial + repairs)
    assert all(CONTROLLED_EXECUTION not in system for system, _body in initial + repairs)
    assert all("pending_actions_not_world_facts" not in body for _system, body in initial + repairs)
    assert not draft.approved and not draft.requests
    assert usage.calls == 3 and usage.proposal_repairs == 1


@pytest.mark.parametrize("protocol", ["native", "json"])
@pytest.mark.parametrize("input_limit", [24000, 34500])
async def test_actual_controlled_initial_and_repair_respect_unchanged_request_limits(
    monkeypatch, protocol, input_limit
):
    admissions = []
    reserve = inference.reserve

    def reserved(settings, usage, size):
        admissions.append(size)
        reserve(settings, usage, size)

    monkeypatch.setattr(inference, "reserve", reserved)
    if protocol == "native" and input_limit == 24000:
        # Full native action definitions already exceed this fixture's small cap.
        # The owner must reject that request before dispatch, rather than widen it.
        with pytest.raises(RecoverableChpmError, match="> 24000 characters"):
            await deliberate(protocol, "staged", input_limit=input_limit)
        assert admissions[-1] > input_limit
        assert all(size <= input_limit for size in admissions[:-1])
        return
    model, _draft, _decision, usage, settings = await deliberate(
        protocol, "staged", input_limit=input_limit
    )
    assert usage.calls == len(admissions) == 3 and usage.proposal_repairs == 1
    assert max(admissions) <= input_limit
    assert usage.input_chars == sum(admissions)
    assert settings.max_input_chars == input_limit
    assert CONTROLLED_EXECUTION in model.initial_requests(protocol)[-1][0]


def test_legacy_default_proposal_text_remains_byte_identical():
    assert hashlib.sha256(prompts.PROPOSE.encode()).hexdigest() == LEGACY_PROPOSAL_HASH


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_compact_choice_survives_action_staging_and_bounded_repair(protocol):
    model, draft, decision, usage, _ = await deliberate(protocol, "staged", detail="compact")
    assert len(decision.proposal.candidates) == 1
    assert decision.selected.kind == "CONTINUE"
    assert len(draft.operations) == 1 and draft.approved and draft.published_results is None
    assert usage.proposal_repairs == 1
    assert all(body["decision_detail"] == "compact" for _, body in model.initial_requests(protocol))
