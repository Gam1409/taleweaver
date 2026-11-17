"""Cognitive action instructions agree with the staged command ownership boundary."""

import json
import re
from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.engine.chpm import cognition, prompts
from backend.engine.chpm.proposal_draft import Draft
from backend.engine.chpm.schema import ProposalOptions, Settings, Usage
from tests.observable_state_support import tools_for, world
from tests.test_chpm_kernel import wire_proposal
from tests.test_chpm_native_notebook_loop import NativeModel, call, turn
from tests.test_chpm_reliability import Replies
from tests.test_chpm_tool_profiles import PROFILES
from tests.test_npc_action_previews import fixture as action_fixture


def proposal(preferred="CONTINUE"):
    value = wire_proposal()
    if preferred == "REFUSE":
        value["candidates"][preferred] = deepcopy(value["candidates"]["CONTINUE"])
        value["candidates"][preferred]["intention"] = "Decline and leave the key where it is."
    value["choice"]["preferred"] = preferred
    value["choice"]["motive_ids"] = [value["candidates"][preferred]["motives"][0]["motive_id"]]
    return value


async def deliberate(protocol, requests, *, actions=True, profile="auto"):
    native = protocol != "json" and not (protocol == "auto" and profile in {"gemma", "qwen"})
    model = (
        NativeModel(
            [
                turn(
                    *(
                        call(f"round-{index}-{position}", name, arguments)
                        for position, (name, arguments) in enumerate(batch)
                    )
                )
                for index, batch in enumerate(requests)
            ]
        )
        if native
        else Replies(
            [
                json.dumps(
                    {
                        "requests": [
                            {"name": name, "arguments": arguments} for name, arguments in batch
                        ]
                    }
                )
                for batch in requests
            ]
        )
    )
    manager, scope, draft = action_fixture()
    tools = tools_for(*world())
    manager._chpm_turn = SimpleNamespace(
        input_id=tools.observation.message_id,
        observable_views={"npc": tools.observable},
        action_drafts={"npc": draft} if actions else {},
    )
    manager._chpm_model_factory = lambda _role: model
    usage = Usage()
    decision, _ = await cognition.deliberate(
        manager,
        Settings(
            mode="live",
            actor_ids=["npc"],
            workflow="integrated",
            tool_protocol=protocol,
            tool_profile=profile,
            action_tools=actions,
            agent_steps=2,
            max_input_chars=64000,
        ),
        usage,
        "npc",
        tools.observation,
        {"authored_goal": "Keep bridges safe"},
        [],
        tools.mind,
    )
    system = model.requests[0][0][0]["content"] if native else model.requests[0][1]
    return decision, usage, draft, scope, system


def test_instruction_names_a_candidate_field_accepted_by_the_wire_contract():
    field = re.search(r"in its (\w+) field", prompts.PROPOSE).group(1)
    value = proposal()
    candidate = value["candidates"]["CONTINUE"]
    candidate[field] = candidate.pop("intention")
    assert Draft.model_validate(value).candidates["CONTINUE"].intention == candidate[field]


async def test_legacy_shadow_proposal_still_names_its_declared_intention_field():
    value = proposal()
    legacy = {
        "appraisal": "Consider a practical next step.",
        "candidates": {
            kind: {key: item for key, item in candidate.items() if key != "motives"}
            for kind, candidate in value["candidates"].items()
        },
    }
    model = Replies([json.dumps(legacy)])
    manager = SimpleNamespace(game_id="session", _chpm_model_factory=lambda _role: model)
    tools = tools_for(*world())
    await cognition.decide(
        manager,
        Settings(mode="shadow", actor_ids=["npc"]),
        Usage(),
        "npc",
        tools.observation,
        {"authored_goal": "Repair the bridge"},
        [],
    )
    field = re.search(r"in its (\w+) field", model.requests[0][1]).group(1)
    candidate = legacy["candidates"]["CONTINUE"]
    candidate[field] = candidate.pop("intention")
    assert (
        ProposalOptions.model_validate(legacy).candidates["CONTINUE"].intention == candidate[field]
    )


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_action_instructions_require_staging_before_submission_and_world_facts_stay_owned(
    protocol,
):
    _, usage, draft, scope, system = await deliberate(
        protocol,
        [[("take_item", {"item_id": "KEY"})], [("submit_decision", proposal())]],
    )

    assert "Choose necessary offered private memory tools OR" not in system
    assert "Submit immediately when current information is sufficient;" not in system
    assert "each chosen API-owned change is staged" in system
    assert "message_plan alone does not stage or execute" in system
    assert "no-action choices need no action call" in system
    assert draft.approved and len(draft.requests) == 1
    assert draft.requests[0].tool == "take_item"
    assert scope.possessions.owners["KEY"] == "__scene__"
    assert usage.calls == 2 and usage.proposal_repairs == 0


@pytest.mark.parametrize("protocol", ["native", "json"])
@pytest.mark.parametrize("preferred", ["DEFER", "REFUSE"])
async def test_action_mode_still_accepts_silence_or_refusal_without_world_commands(
    protocol, preferred
):
    decision, usage, draft, _, _ = await deliberate(
        protocol, [[("submit_decision", proposal(preferred))]]
    )
    assert decision.selected.kind == preferred
    assert draft.approved and draft.requests == []
    assert usage.calls == 1 and usage.proposal_repairs == 0


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_memory_only_mode_retains_immediate_grounded_submission(protocol):
    _, usage, draft, _, system = await deliberate(
        protocol, [[("submit_decision", proposal())]], actions=False
    )
    assert "Submit immediately when current information is sufficient;" in system
    assert "each chosen API-owned change is staged" not in system
    assert "message_plan alone does not stage or execute" not in system
    assert not draft.approved and draft.requests == []
    assert usage.calls == 1


@pytest.mark.parametrize("profile", PROFILES)
async def test_selected_profiles_keep_action_staging_and_final_acceptance_in_the_same_owners(
    profile,
):
    decision, usage, draft, scope, _system = await deliberate(
        "auto",
        [[("take_item", {"item_id": "KEY"})], [("submit_decision", proposal())]],
        profile=profile,
    )
    assert decision.selected.kind == "CONTINUE"
    assert draft.approved and len(draft.requests) == 1
    assert draft.requests[0].tool == "take_item"
    assert scope.possessions.owners["KEY"] == "__scene__"
    assert usage.calls == 2 and usage.proposal_repairs == 0
