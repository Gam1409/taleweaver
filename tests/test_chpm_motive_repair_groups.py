"""One proposal repair sees every independent grounding fault without changing the choice."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.engine.chpm import cognition
from backend.engine.chpm.errors import ProposalRejectedError
from backend.engine.chpm.host_state import record
from backend.engine.chpm.proposal_draft import Draft
from backend.engine.chpm.schema import Settings, Usage
from tests.chpm_reference_fixture import response as reference_response
from tests.chpm_repair_fixture import corrections
from tests.test_chpm_agent_tools import current
from tests.test_chpm_host_state import mind, source
from tests.test_chpm_integrated_workflow import deliberate
from tests.test_chpm_kernel import observation, wire_proposal
from tests.test_chpm_native_notebook_loop import NativeModel, call, turn


def proposals(case, *, structural=False, intra=False):
    original = wire_proposal()
    chosen = deepcopy(original["candidates"]["CONTINUE"])
    alternative = deepcopy(original["candidates"]["DEFER"])
    preferred, invalid = ("CONTINUE", "REFUSE") if case == "key" else ("INITIATE", "CONTINUE")
    original["candidates"] = {
        preferred: chosen,
        invalid: deepcopy(alternative),
        "DEFER": deepcopy(alternative),
    }
    original["choice"]["preferred"] = preferred
    for kind in (invalid, "DEFER"):
        original["candidates"][kind]["motives"][0]["effect"] = "tension"
    if case == "key":
        original["candidates"]["DEFER"]["motives"][0]["motive_id"] = "goal1"
        original["candidates"][invalid]["motives"].append(
            deepcopy(original["candidates"]["DEFER"]["motives"][0])
        )
    if intra:
        motive = original["candidates"][invalid]["motives"][0]
        motive["motive_id"] = "unavailable-motive"
        original["candidates"][invalid]["motives"] = [deepcopy(motive), deepcopy(motive)]
    corrected = deepcopy(original)
    for kind in (invalid, "DEFER"):
        corrected["candidates"][kind]["motives"] = [
            {
                "motive_id": "character",
                "effect": "supports",
                "relevance": "A genuine independent reason to consider this alternative.",
            }
        ]
    if structural:
        original["choice"]["reason"] = "x" * 301
        corrected["choice"]["reason"] = "Continue the grounded preferred course."
    return original, corrected, (invalid, "DEFER")


class RepairModel(NativeModel):
    def __init__(self, original, corrected, invalid, *, structural=False, intra=False):
        super().__init__([turn(call("decision", "submit_decision", original))])
        self.original = original
        self.corrected = corrected
        self.invalid = invalid
        self.structural = structural
        self.intra = intra
        self.feedback = None

    async def aexecute_simple_task(self, system, content, model, **kwargs):
        self.json_requests.append((system, content, kwargs))
        payload = json.loads(content)
        if kwargs.get("phase") != "proposal_repair":
            value = self.original
            if kwargs.get("phase") == "integrated_decision":
                value = {"requests": [{"name": "submit_decision", "arguments": value}]}
            return reference_response(json.dumps(value), payload)
        self.feedback = payload["proposal_feedback"]
        issues = [
            issue
            for group in self.feedback.get("recommended_repair_groups", [])
            for issue in group["issues"]
        ]
        support = {issue["path"] for issue in issues if issue["type"] == "motive_own_support"}
        assert support == {f"/candidates/{kind}/motives" for kind in self.invalid}
        assert self.feedback["motive_error_count"] >= 2
        if self.intra:
            assert {"motive_unavailable", "motive_duplicate", "motive_own_support"} <= {
                issue["type"] for issue in issues
            }
        if self.structural:
            assert any(issue["path"] == "/choice/reason" for issue in issues)
            assert self.feedback["structural_error_count"] >= 1
        changes = [
            (f"/candidates/{kind}/motives", self.corrected["candidates"][kind]["motives"])
            for kind in self.invalid
        ]
        if self.structural:
            changes.append(("/choice/reason", self.corrected["choice"]["reason"]))
        return corrections(*changes)


@pytest.mark.parametrize("protocol", ["native", "json", "staged"])
@pytest.mark.parametrize("case", ["key", "cup"])
async def test_all_nonchosen_grounding_faults_reach_the_existing_single_repair(case, protocol):
    original, corrected, invalid = proposals(case)
    before = deepcopy(original)
    model = RepairModel(original, corrected, invalid)

    (decision, _), usage = await deliberate(
        model,
        steps=0 if protocol == "staged" else 2,
        protocol="json" if protocol == "staged" else protocol,
    )

    assert decision.choice_preference.preferred == original["choice"]["preferred"]
    assert decision.choice_preference.motive_ids == original["choice"]["motive_ids"]
    assert decision.choice_preference.reason == original["choice"]["reason"]
    assert usage.calls == 2 and usage.proposal_repairs == 1
    assert len(model.requests) + len(model.json_requests) == 2
    assert original == before


@pytest.mark.parametrize("protocol", ["native", "json", "staged"])
@pytest.mark.parametrize("intra", [False, True])
async def test_structural_failure_keeps_independently_knowable_motive_faults(protocol, intra):
    original, corrected, invalid = proposals("key", structural=True, intra=intra)
    model = RepairModel(original, corrected, invalid, structural=True, intra=intra)

    (decision, _), usage = await deliberate(
        model,
        steps=0 if protocol == "staged" else 2,
        protocol="json" if protocol == "staged" else protocol,
    )

    assert decision.choice_preference.preferred == original["choice"]["preferred"]
    assert decision.choice_preference.motive_ids == original["choice"]["motive_ids"]
    assert decision.choice_preference.reason == corrected["choice"]["reason"]
    assert usage.calls == 2 and usage.proposal_repairs == 1


@pytest.mark.parametrize("protocol", ["native", "json", "staged"])
async def test_repair_does_not_silently_accept_remaining_ungrounded_candidate_or_call_again(
    protocol,
):
    original, corrected, invalid = proposals("key")
    corrected["candidates"]["DEFER"]["motives"] = original["candidates"]["DEFER"]["motives"]
    model = RepairModel(original, corrected, invalid)

    with pytest.raises(ProposalRejectedError, match="DEFER lacks a supporting"):
        await deliberate(
            model,
            steps=0 if protocol == "staged" else 2,
            protocol="json" if protocol == "staged" else protocol,
        )

    assert len(model.requests) + len(model.json_requests) == 2


async def test_complete_diagnostics_do_not_consume_the_reserved_review_budget():
    original, corrected, invalid = proposals("key")
    model = RepairModel(original, corrected, invalid)

    with pytest.raises(ProposalRejectedError, match="reserved request budget"):
        await deliberate(model, max_calls=4)

    assert len(model.requests) + len(model.json_requests) == 1


@pytest.mark.parametrize("protocol", ["native", "json", "staged"])
async def test_cup_recorded_motive_combination_does_not_promote_world_observation_to_personal_support(
    protocol,
):
    original, corrected, invalid = proposals("cup")
    for kind, personal in (("CONTINUE", "goal1"), ("DEFER", "character")):
        original["candidates"][kind]["motives"] = [
            {"motive_id": personal, "effect": "tension", "relevance": "A personal tradeoff."},
            {"motive_id": "report-e1", "effect": "supports", "relevance": "The observed cup."},
        ]
    model = RepairModel(original, corrected, invalid)
    value = current(
        record(mind(), source("scene", "The cup is on the desk.", "narration"), minute=1)
    )
    usage = Usage()
    manager = SimpleNamespace(game_id="session", _chpm_model_factory=lambda _role: model)

    decision, _ = await cognition.deliberate(
        manager,
        Settings(
            mode="live",
            actor_ids=["npc"],
            workflow="integrated",
            agent_steps=0 if protocol == "staged" else 2,
            tool_protocol="json" if protocol == "staged" else protocol,
        ),
        usage,
        "npc",
        observation(),
        {"authored_goal": "Keep bridges safe"},
        [],
        value,
    )

    assert decision.choice_preference.preferred == "INITIATE"
    assert decision.choice_preference.motive_ids == original["choice"]["motive_ids"]
    assert usage.calls == 2 and usage.proposal_repairs == 1
    assert len(model.requests) + len(model.json_requests) == 2
    assert (
        model.feedback["rejected_proposal"]["candidates"]
        == Draft.model_validate(original).model_dump(mode="json")["candidates"]
    )
