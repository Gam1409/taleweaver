"""The experimental workflow shares scoped tools and the existing decision validator."""

import json
from types import SimpleNamespace

import pytest

from backend.engine.chpm import cognition
from backend.engine.chpm.notebook import NotebookWorkspace
from backend.engine.chpm.notebook_tools import NotebookDraft
from backend.engine.chpm.schema import KernelState, Settings, Usage
from tests.chpm_repair_fixture import corrections
from tests.test_chpm_agent_tools import current
from tests.test_chpm_kernel import observation, wire_proposal
from tests.test_chpm_native_notebook_loop import NativeModel, call, turn
from tests.test_chpm_semantic_choice import fixture


async def deliberate(model, *, steps=2, notebook=None, protocol="native", max_calls=8):
    value, _, _, _ = fixture()
    value = current(value)
    settings = Settings(
        mode="live",
        actor_ids=["npc"],
        agent_steps=steps,
        workflow="integrated",
        tool_protocol=protocol,
        max_calls_per_turn=max_calls,
    )
    usage = Usage()
    host = SimpleNamespace(game_id="session", _chpm_model_factory=lambda _role: model)
    result = await cognition.deliberate(
        host,
        settings,
        usage,
        "npc",
        observation(),
        {"authored_goal": "Repair the bridge"},
        [],
        value,
        notebook=notebook,
    )
    return result, usage


def test_legacy_settings_keep_staged_workflow_and_unknown_timing_mode():
    original = KernelState().model_dump()
    original["settings"].pop("workflow", None)
    original["usage"].pop("workflow", None)
    restored = KernelState.model_validate(original)
    assert restored.settings.workflow == "staged"
    assert restored.usage.workflow is None
    assert restored.schema_version == original["schema_version"]


async def test_direct_decision_skips_the_separate_memory_planning_call():
    model = NativeModel([turn(call("decision", "submit_decision", wire_proposal()))])
    (decision, _), usage = await deliberate(model)
    assert usage.calls == len(model.requests) == 1
    assert usage.workflow == "integrated"
    assert decision.choice_preference.preferred == "CONTINUE"
    assert decision.agent_audit == []
    assert model.max_tokens == 1200


async def test_tool_results_rebuild_bound_sources_before_final_decision():
    model = NativeModel(
        [
            turn(call("inspect", "inspect_self", {})),
            turn(call("decision", "submit_decision", wire_proposal())),
        ]
    )
    (decision, _), usage = await deliberate(model, steps=1)
    assert usage.calls == 2
    assert decision.agent_audit[0]["requests"][0]["tool"] == "inspect_self"
    assert decision.agent_audit[0]["results"][0]["status"] == "ok"
    final_tools = model.requests[1][1]
    assert [item["function"]["name"] for item in final_tools] == ["submit_decision"]
    context = json.loads(model.requests[1][0][1]["content"])
    assert context["remaining_rounds"] == 0
    assert context["agent_lookup_status"] == [{"tool": "inspect_self", "status": "ok"}]


async def test_mixed_decision_and_memory_write_never_executes_the_write():
    draft = NotebookDraft(NotebookWorkspace())
    model = NativeModel(
        [
            turn(
                call(
                    "write",
                    "notebook_write",
                    {"path": "/note", "value": "private", "expected_revision": 0},
                ),
                call("decision", "submit_decision", wire_proposal()),
            )
        ]
    )
    with pytest.raises(ValueError):
        await deliberate(model, notebook=draft)
    assert not draft.workspace.changed
    assert not draft.committable


async def test_portable_protocol_can_submit_the_same_validated_decision():
    from tests.test_chpm_reliability import Replies

    model = Replies(
        [json.dumps({"requests": [{"name": "submit_decision", "arguments": wire_proposal()}]})]
    )
    (decision, _), usage = await deliberate(model, protocol="json")
    assert usage.calls == 1 and usage.workflow == "integrated"
    assert decision.choice_preference.preferred == "CONTINUE"


async def test_zero_tool_rounds_keep_the_existing_decision_path():
    from tests.test_chpm_reliability import Replies

    model = Replies([json.dumps(wire_proposal())])
    (decision, _), usage = await deliberate(model, steps=0)
    assert usage.calls == 1 and usage.workflow == "staged"
    assert decision.choice_preference.preferred == "CONTINUE"


@pytest.mark.parametrize("parallel", [False, True])
async def test_semantic_rejection_uses_the_existing_shared_repair_once(parallel):
    from backend.engine.chpm import parallel_budget, performance

    original = wire_proposal()
    original["choice"]["motive_ids"] = ["unknown-motive"]

    class RepairModel(NativeModel):
        async def aexecute_simple_task(self, system, content, model, **kwargs):
            self.json_requests.append((system, content, kwargs))
            return corrections(("/choice/motive_ids", ["goal1"]))

    model = RepairModel([turn(call("decision", "submit_decision", original))])
    token = performance.actor_id.set("npc")
    try:
        with parallel_budget.reserve(["npc", "other"] if parallel else [], 3):
            (decision, _), usage = await deliberate(model)
    finally:
        performance.actor_id.reset(token)
    assert usage.calls == 2 and usage.proposal_repairs == 1
    assert len(model.requests) == len(model.json_requests) == 1
    feedback = json.loads(model.json_requests[0][1])["proposal_feedback"]
    assert "unknown-motive" in feedback["error"]
    assert decision.choice_preference.motive_ids == ["goal1"]


async def test_transport_failure_preserves_notes_without_retrying():
    from backend.engine.chpm.errors import InferenceUnavailableError

    draft = NotebookDraft(NotebookWorkspace())
    model = NativeModel([TimeoutError("Offline transport failure")])
    with pytest.raises(InferenceUnavailableError):
        await deliberate(model, notebook=draft)
    assert len(model.requests) == 1 and model.json_requests == []
    assert not draft.committable and not draft.workspace.changed


async def test_functions_are_unavailable_after_the_configured_memory_rounds():
    model = NativeModel(
        [
            turn(call("first", "inspect_self", {})),
            turn(call("extra", "inspect_self", {})),
        ]
    )
    with pytest.raises(ValueError, match="unavailable function"):
        await deliberate(model, steps=1)
    assert len(model.requests) == 2
