"""Three bounded memory rounds can correct an error and read the staged correction."""

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.engine.chpm import agent
from backend.engine.chpm.errors import RecoverableChpmError
from backend.engine.chpm.notebook import NotebookWorkspace
from backend.engine.chpm.notebook.tree import lookup
from backend.engine.chpm.notebook_tools import NotebookDraft
from backend.engine.chpm.schema import Settings, Usage
from tests.test_chpm_host_state import mind
from tests.test_chpm_json_tool_port import TextModel
from tests.test_chpm_kernel import observation
from tests.test_chpm_native_notebook_loop import NativeModel, call, investigate, turn

NOTE = {"reminder": "Inspect the bridge before drawing a conclusion.", "certain": False}
ORIGINAL = b'{"private":"An earlier thought."}'


def model_for(protocol, batches):
    if protocol == "native":
        return NativeModel(
            [
                turn(*(call(f"round-{index}", name, arguments) for name, arguments in batch))
                for index, batch in enumerate(batches)
            ]
        )
    return TextModel(
        [
            json.dumps(
                {"requests": [{"name": name, "arguments": arguments} for name, arguments in batch]}
            )
            for batch in batches
        ]
    )


def context_for(model, protocol, index):
    if protocol == "json":
        return model.calls[index][1]
    messages = model.requests[index][0]
    values = [json.loads(message["content"]) for message in messages if message["role"] == "user"]
    context = dict(values[0])
    for value in values[1:]:
        context.update(value.get("host_context_update", {}))
    return {**context, "conversation": messages}


def correlated_results(context):
    return [
        (
            message["tool_call_id"],
            json.loads(message["content"])
            if "content" in message
            else lookup(context, message["content_ref"][1:]),
        )
        for message in context["conversation"]
        if message["role"] == "tool"
    ]


def prior_calls(context):
    return [item for message in context["conversation"] for item in message.get("tool_calls", [])]


async def investigate_at_budget(model, draft, protocol, input_budget, usage=None):
    usage = usage or Usage()
    tools, audit = await agent.investigate(
        SimpleNamespace(game_id="session", _chpm_model_factory=lambda _role: model),
        Settings(
            mode="live",
            actor_ids=["npc"],
            notebook_enabled=True,
            tool_protocol=protocol,
            agent_steps=3,
            max_input_chars=input_budget,
        ),
        usage,
        mind(),
        observation(),
        {},
        notebook=draft,
    )
    return tools, audit, usage


def request_sizes(model, protocol):
    if protocol == "native":
        return [
            len(json.dumps({"messages": messages, "tools": tools}, ensure_ascii=False))
            for messages, tools, _ in model.requests
        ]
    return [
        len(system) + len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        for system, payload, _, _ in model.calls
    ]


def recovery_model(protocol, failure):
    missing_parent = failure == "missing_path"
    first = {
        "path": "/missing/child" if missing_parent else "/private",
        "value": NOTE,
        "expected_revision": 4 if missing_parent else 3,
    }
    return model_for(
        protocol,
        [
            [("notebook_write", first)],
            [
                (
                    "notebook_write",
                    {
                        "path": "/missing" if missing_parent else "/private",
                        "value": {"child": NOTE} if missing_parent else NOTE,
                        "expected_revision": 4,
                    },
                )
            ],
            [("notebook_read", {"path": first["path"]})],
            [("notebook_write", {"path": "/fourth", "value": True, "expected_revision": 5})],
        ],
    )


@pytest.mark.parametrize("protocol", ["native", "json"])
@pytest.mark.parametrize("failure", ["missing_path", "stale_revision"])
async def test_three_rounds_correct_an_error_then_read_the_latest_staged_value(protocol, failure):
    model = recovery_model(protocol, failure)
    draft = NotebookDraft(NotebookWorkspace(ORIGINAL, revision=4))

    tools, audit, usage = await investigate_at_budget(model, draft, protocol, 24000)

    requests = model.requests if protocol == "native" else model.calls
    assert len(requests) == usage.calls == 3
    assert max(request_sizes(model, protocol)) <= 24000
    assert usage.input_chars == sum(request_sizes(model, protocol))
    contexts = [context_for(model, protocol, index) for index in range(3)]
    assert [context["remaining_rounds"] for context in contexts] == [3, 2, 1]
    assert [context["personal_notebook"]["revision"] for context in contexts] == [4, 4, 5]
    second_feedback = correlated_results(contexts[1])
    assert len(second_feedback) == 1
    assert second_feedback[0][0] == prior_calls(contexts[1])[0]["id"]
    assert second_feedback[0][1]["status"] == failure
    assert second_feedback[0][1]["revision"] == 4
    third_feedback = correlated_results(contexts[2])
    assert [identifier for identifier, _ in third_feedback] == [
        item["id"] for item in prior_calls(contexts[2])
    ]
    assert [result["status"] for _, result in third_feedback] == [failure, "ok"]
    assert third_feedback[1][1]["revision"] == 5
    assert json.loads(tools.notebook.reads[-1]["json_fragment"]) == NOTE
    expected = (
        {"private": "An earlier thought.", "missing": {"child": NOTE}}
        if failure == "missing_path"
        else {"private": NOTE}
    )
    assert json.loads(draft.workspace.canonical_bytes) == expected
    assert draft.workspace.base_revision == 4 and draft.workspace.revision == 5
    assert draft.committable and draft.context()["pending_changes"]
    assert [item["stop"] for item in audit] == ["continue", "continue", "step_limit"]
    assert NOTE["reminder"] not in json.dumps(audit)


@pytest.mark.parametrize("protocol", ["native", "json"])
@pytest.mark.parametrize("failure", ["missing_path", "stale_revision"])
async def test_8k_budget_rejects_oversized_recovery_before_dispatch_and_disables_commit(
    protocol, failure
):
    model = recovery_model(protocol, failure)
    draft, usage = NotebookDraft(NotebookWorkspace(ORIGINAL, revision=4)), Usage()

    with pytest.raises(RecoverableChpmError, match="input exceeds its configured size limit"):
        await investigate_at_budget(model, draft, protocol, 8000, usage)

    requests = model.requests if protocol == "native" else model.calls
    assert len(requests) == usage.calls == (0 if protocol == "native" else 1)
    assert all(size <= 8000 for size in request_sizes(model, protocol))
    assert usage.input_chars == sum(request_sizes(model, protocol))
    assert draft.workspace.canonical_bytes == ORIGINAL and draft.workspace.revision == 4
    assert not draft.workspace.changed and not draft.committable
    assert draft.context()["pending_changes"] is False


@pytest.mark.parametrize("protocol", ["native", "json"])
@pytest.mark.parametrize("ready_round", [1, 2])
async def test_three_round_allowance_stops_early_when_no_further_tool_is_requested(
    protocol, ready_round
):
    batches = [[("notebook_info", {})]] * (ready_round - 1)
    model = model_for(
        protocol,
        [*batches, [], [("notebook_write", {"value": NOTE, "expected_revision": 0})]],
    )

    tools, audit, usage = await investigate(model, steps=3, protocol=protocol)

    requests = model.requests if protocol == "native" else model.calls
    assert len(requests) == usage.calls == ready_round
    assert len(audit) == ready_round and audit[-1]["stop"] == "ready"
    assert tools.notebook.workspace.canonical_bytes == b"{}" and tools.notebook.committable
    assert not tools.notebook.workspace.changed


def test_a_fourth_memory_round_is_rejected_by_the_production_settings_contract():
    with pytest.raises(ValidationError):
        Settings(mode="live", actor_ids=["npc"], notebook_enabled=True, agent_steps=4)
