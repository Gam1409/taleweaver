"""Protocol corrections consume existing rounds without replaying private operations."""

import asyncio
import json
from dataclasses import replace

import pytest

from backend.core.llm_completion_capture import record_completion
from backend.core.llm_tool_turn import ToolTurn
from backend.engine.chpm.notebook import NotebookWorkspace
from backend.engine.chpm.notebook_tools import NotebookDraft
from tests.test_chpm_integrated_workflow import deliberate
from tests.test_chpm_kernel import wire_proposal
from tests.test_chpm_native_notebook_loop import NativeModel, call, turn
from tests.test_chpm_reliability import Replies


@pytest.mark.parametrize(
    "raw",
    [
        '{"candidates":{},"choice":{},"padding":"' + "x" * 32768 + '"}',
        '{"candidates":{},"choice":{},"nested":' + "[" * 70 + "0" + "]" * 70 + "}",
        '{"candidates":{},"choice":{},"value":1e999}',
        '{"candidates":{"A":1],"choice":{},"choice":{}}',
        '{"candidates":{"A":1],"choice":{}] ',
        '{"candidates":{"A":1],"choice":{}} trailing text',
        '{"requests":[{"name":"inspect_self","arguments":{}]}',
        '{"candidates":{},"choice":{},"value":"\\ud800"}',
    ],
)
def test_native_text_final_keeps_tool_argument_resource_and_strict_json_guards(raw):
    from backend.engine.chpm.integrated_protocol import _proposal_content

    assert not _proposal_content(raw)


def final(identifier="final"):
    return turn(call(identifier, "submit_decision", wire_proposal()))


def mixed(identifier="write"):
    return turn(
        call(identifier, "notebook_write", {"path": "/bad", "value": 1, "expected_revision": 0}),
        call(identifier + "_final", "submit_decision", wire_proposal()),
    )


@pytest.mark.parametrize(
    "raw,code",
    [
        ("{}", "missing_requests"),
        ('{"requests":[],"notebook_info":null}', "unexpected_fields"),
        ('{"requests":[{},{},{}]}', "too_many_requests"),
        ('{"requests":[],"requests":[]}', "invalid_json"),
    ],
)
def test_portable_error_codes_are_specific_and_do_not_echo_model_fields(raw, code):
    from backend.core.llm_tool_turn import InvalidToolTurnError
    from backend.engine.chpm.json_tool_port import _calls

    with pytest.raises(InvalidToolTurnError) as caught:
        _calls(raw)
    assert caught.value.code == code
    assert "notebook_info" not in str(caught.value)


async def test_unavailable_function_is_explained_without_executing_it():
    model = NativeModel([turn(call("unknown", "imaginary_function", {})), final()])
    (decision, _), usage = await deliberate(model, steps=1)
    assert usage.calls == 2 and decision.agent_audit[0]["error_type"] == "unavailable_function"


async def test_mixed_batch_gets_one_explanation_and_never_executes_its_write():
    draft = NotebookDraft(NotebookWorkspace())
    model = NativeModel([mixed(), final()])
    (decision, _), usage = await deliberate(model, steps=1, notebook=draft)
    assert usage.calls == len(model.requests) == 2
    assert draft.committable and not draft.workspace.changed
    feedback = json.loads(model.requests[1][0][-1]["content"])["host_protocol_feedback"]
    assert feedback["code"] == "mixed_submission" and feedback["operations_applied"] is False
    assert "separately" in feedback["message"]
    assert [x["function"]["name"] for x in model.requests[1][1]] == ["submit_decision"]
    assert decision.agent_audit[0]["stop"] == "invalid_envelope"
    assert not any(m.get("tool_calls") for m in model.requests[1][0])


async def test_complete_portable_format_error_can_be_corrected_within_existing_rounds():
    model = Replies(
        [
            '{"requests":[],"unexpected":null}',
            json.dumps({"requests": [{"name": "submit_decision", "arguments": wire_proposal()}]}),
        ]
    )
    (decision, _), usage = await deliberate(model, steps=1, protocol="json")
    assert usage.calls == 2 and not usage.proposal_repairs
    assert decision.choice_preference.preferred == "CONTINUE"
    assert decision.agent_audit[0]["stop"] == "invalid_envelope"
    assert decision.agent_audit[0]["error_type"] == "unexpected_fields"


async def test_unclosed_portable_final_names_the_array_in_the_existing_one_correction():
    canary = "PRIVATE: a string containing fake closers }]} and a quoted bracket"
    item = {"name": "submit_decision", "arguments": {"nested": [{"data": canary}]}}
    malformed = '{ "requests" : [ ' + json.dumps(item) + " }"
    reply = json.dumps({"requests": [{"name": "submit_decision", "arguments": wire_proposal()}]})
    model = Replies([malformed, reply])
    (decision, _), usage = await deliberate(model, steps=1, protocol="json")
    assert len(model.requests) == usage.calls == 2 and not usage.proposal_repairs
    history = model.requests[1][2]["conversation"]
    feedback = next(
        json.loads(m["content"])["host_protocol_feedback"]
        for m in history
        if "host_protocol_feedback" in m.get("content", "")
    )
    assert feedback["code"] == decision.agent_audit[0]["error_type"] == "unclosed_requests_array"
    assert feedback["operations_applied"] is False
    assert "requests array" in feedback["message"] and "}]}" in feedback["message"]
    assert '{"requests":[{"name":"submit_decision","arguments":{}}]}' in feedback["message"]
    assert canary not in json.dumps(history) and not decision.agent_audit[0]["requests"]


@pytest.mark.parametrize(
    "raw",
    [
        '{"requests":[{"name":"submit_decision","arguments":{"v":[1}}}}',
        '{"requests":[{"name":"submit_decision","arguments":{}},{"name":"submit_decision","arguments":{}}}',
        '{"requests":[{"name":"submit_decision","arguments":{},"arguments":{}}}',
        '{"requests":[{"name":"submit_decision","arguments":{},"extra":true}}',
        '{"requests":[{"name":"submit_decision","arguments":"data"}}',
        '{"requests":[{"name":"submit_decision","arguments":{"v":1e999}}}',
        '{"requests":[{"name":"submit_decision","arguments":{"v":"\\ud800"}}}',
        '{"requests":[{"name":"submit_decision","arguments":{}}} trailing',
        '{"requests":[{"name":"submit_decision","arguments":{}}',
        '{"actions":[{"name":"submit_decision","arguments":{}}}',
    ],
)
def test_ambiguous_or_mixed_json_errors_keep_the_generic_guard(raw):
    from backend.core.llm_tool_turn import InvalidToolTurnError
    from backend.engine.chpm.json_tool_port import _calls

    with pytest.raises(InvalidToolTurnError) as caught:
        _calls(raw)
    assert caught.value.code == "invalid_json"


@pytest.mark.parametrize(
    "response,code",
    [
        ('{"requests":', "invalid_json"),
        ('{"candidates":{},"choice":{}}', "missing_requests"),
        ('{"requests":[{},{},{}]}', "too_many_requests"),
    ],
)
async def test_portable_feedback_explains_the_specific_format_failure(response, code):
    model = Replies(
        [
            response,
            json.dumps({"requests": [{"name": "submit_decision", "arguments": wire_proposal()}]}),
        ]
    )
    (decision, _), usage = await deliberate(model, steps=1, protocol="json")
    assert usage.calls == 2 and not usage.proposal_repairs
    assert decision.agent_audit[0]["error_type"] == code


async def test_prior_successful_write_is_retained_and_not_replayed_after_invalid_batch():
    draft = NotebookDraft(NotebookWorkspace())
    first = turn(
        call("first", "notebook_write", {"path": "/note", "value": "mine", "expected_revision": 0})
    )
    model = NativeModel([first, mixed(), final()])
    (decision, _), usage = await deliberate(model, steps=2, notebook=draft)
    assert usage.calls == 3 and draft.committable
    assert draft.workspace.revision == 1
    assert len(decision.agent_audit) == 2
    assert [x["stop"] for x in decision.agent_audit] == ["continue", "invalid_envelope"]


async def test_second_protocol_error_stops_instead_of_using_a_third_response():
    draft = NotebookDraft(NotebookWorkspace())
    model = NativeModel([mixed("first"), mixed("second"), final()])
    with pytest.raises(ValueError, match="separately"):
        await deliberate(model, steps=3, notebook=draft)
    assert len(model.requests) == 2
    assert not draft.committable and not draft.workspace.changed


async def test_cancellation_after_a_successful_write_does_not_retry_or_commit():
    import asyncio

    draft = NotebookDraft(NotebookWorkspace())
    write = turn(
        call("write", "notebook_write", {"path": "/note", "value": "mine", "expected_revision": 0})
    )
    model = NativeModel([write, asyncio.CancelledError(), final()])
    with pytest.raises(asyncio.CancelledError):
        await deliberate(model, steps=3, notebook=draft)
    assert len(model.requests) == 2 and not draft.committable


async def test_duplicate_call_ids_are_not_reintroduced_into_native_history():
    duplicate = turn(call("same", "inspect_self", {}), call("same", "notebook_info", {}))
    model = NativeModel([duplicate, final()])
    (decision, _), usage = await deliberate(model, steps=1)
    assert usage.calls == 2 and decision.agent_audit[0]["error_type"] == "invalid_call_envelope"
    assert not any(m.get("tool_calls") for m in model.requests[1][0])


async def test_two_observers_each_have_their_own_correction_allowance():
    import asyncio

    first, second = NativeModel([mixed(), final()]), NativeModel([mixed(), final()])
    results = await asyncio.gather(deliberate(first, steps=1), deliberate(second, steps=1))
    assert all(usage.calls == 2 for _, usage in results)
    assert all(len(decision.agent_audit) == 1 for (decision, _), _ in results)


@pytest.mark.parametrize("finish", ["length", "max_tokens", "content_filter"])
async def test_truncation_and_unsupported_finishes_are_not_retried(finish):
    model = NativeModel(
        [ToolTurn({"role": "assistant", "content": "{}"}, finish_reason=finish), final()]
    )
    with pytest.raises(ValueError):
        await deliberate(model, steps=2)
    assert len(model.requests) == 1


async def test_native_text_final_uses_the_existing_validator_without_a_repair_request():
    model = NativeModel(
        [
            ToolTurn(
                {"role": "assistant", "content": json.dumps(wire_proposal())}, finish_reason="stop"
            )
        ]
    )
    (decision, _), usage = await deliberate(model)
    assert usage.calls == 1 and not usage.proposal_repairs
    assert usage.format_repairs == 1
    assert decision.choice_preference.preferred == "CONTINUE"


@pytest.mark.parametrize("stale", [False, True])
async def test_complete_text_decision_with_one_wrong_closer_stays_bound_to_its_dispatch(stale):
    class TextModel(NativeModel):
        async def aexecute_tool_turn(self, messages, tools, model, **kwargs):
            final = await super().aexecute_tool_turn(messages, tools, model, **kwargs)
            body = json.loads(final.calls[0].arguments_raw)
            body.pop("reference_scope")
            if stale:
                body["reference_scope"] = "another-observer-window"
            candidates = json.dumps(body.pop("candidates"))
            text = '{"candidates":' + candidates[:-1] + "]," + json.dumps(body)[1:]
            return replace(
                final,
                calls=(),
                assistant_message={"role": "assistant", "content": text},
                finish_reason="stop",
            )

    model = TextModel([final()])
    if stale:
        with pytest.raises(ValueError, match="remains invalid"):
            await deliberate(model)
        assert len(model.json_requests) == 1
    else:
        (decision, _), usage = await deliberate(model)
        assert decision.choice_preference.preferred == "CONTINUE"
        assert usage.calls == 1 and not model.json_requests
    tools = model.requests[0][1]
    parameters = next(
        t["function"]["parameters"] for t in tools if t["function"]["name"] == "submit_decision"
    )
    assert "reference_scope" not in parameters["required"]
    assert len(model.requests) == 1


async def test_oversize_native_final_cannot_bypass_the_function_argument_limit():
    content = json.dumps(wire_proposal()) + " " * 40000
    model = NativeModel(
        [ToolTurn({"role": "assistant", "content": content}, finish_reason="stop"), final()]
    )
    (decision, _), usage = await deliberate(model, steps=1)
    assert usage.calls == 2
    assert decision.agent_audit[0]["error_type"] == "missing_submission"


async def test_concurrent_decisions_each_have_their_own_single_correction():
    first_model = NativeModel([mixed("first"), final("first_final")])
    second_model = NativeModel([mixed("second"), final("second_final")])
    values = await asyncio.gather(
        deliberate(first_model, steps=1), deliberate(second_model, steps=1)
    )
    for (decision, _), usage in values:
        assert usage.calls == 2 and len(decision.agent_audit) == 1
    assert len(first_model.requests) == len(second_model.requests) == 2


async def test_empty_portable_final_uses_a_round_correction_instead_of_semantic_repair():
    model = Replies(
        [
            '{"requests":[]}',
            json.dumps({"requests": [{"name": "submit_decision", "arguments": wire_proposal()}]}),
        ]
    )
    (decision, _), usage = await deliberate(model, steps=1, protocol="json")
    assert usage.calls == 2 and not usage.proposal_repairs
    assert decision.agent_audit[0]["error_type"] == "missing_submission"


async def test_empty_portable_final_after_last_round_cannot_request_a_proposal_repair():
    draft = NotebookDraft(NotebookWorkspace())
    model = Replies(
        [
            json.dumps({"requests": [{"name": "inspect_self", "arguments": {}}]}),
            '{"requests":[]}',
        ]
    )
    with pytest.raises(ValueError, match="No final submission"):
        await deliberate(model, steps=1, notebook=draft, protocol="json")
    assert len(model.requests) == 2 and not draft.committable


async def test_exhausted_call_budget_cannot_dispatch_a_corrective_request_after_write():
    draft = NotebookDraft(NotebookWorkspace())
    write = turn(
        call("write", "notebook_write", {"path": "/note", "value": "mine", "expected_revision": 0})
    )
    model = NativeModel([write, mixed(), final()])
    with pytest.raises(ValueError, match="request budget exhausted"):
        await deliberate(model, steps=3, notebook=draft, max_calls=2)
    assert len(model.requests) == 2 and draft.workspace.revision == 1
    assert not draft.committable


async def test_correction_does_not_exceed_the_audit_limit_on_the_final_available_round():
    model = NativeModel(
        [
            turn(call("first", "inspect_self", {})),
            turn(call("second", "inspect_self", {})),
            mixed(),
            final(),
        ]
    )
    (decision, _), usage = await deliberate(model, steps=3)
    assert usage.calls == 4 and len(decision.agent_audit) == 3


class ProviderPayloads(NativeModel):
    async def aexecute_tool_turn(self, *args, **kwargs):
        from backend.core.llm_tool_turn import _turn

        result = await super().aexecute_tool_turn(*args, **kwargs)
        record_completion(result)
        return _turn(result)


@pytest.mark.parametrize(
    "finish,native",
    [
        ("content_filter", None),
        ("stop", "filtered"),
        ("unknown", None),
        ("stop", "MAX_TOKENS"),
        ("stop", "compaction"),
    ],
)
@pytest.mark.parametrize("broken", ["content", "call"])
async def test_failed_provider_finish_wins_over_structural_errors(finish, native, broken):
    message = {"role": "assistant", "content": [] if broken == "content" else None}
    if broken == "call":
        message["tool_calls"] = [{"id": "bad"}]
    choice = {"finish_reason": finish, "message": message}
    if native:
        choice["provider_specific_fields"] = {"native_finish_reason": native}
    model = ProviderPayloads([{"choices": [choice]}, {"choices": []}])
    with pytest.raises(ValueError):
        await deliberate(model, steps=3)
    assert len(model.requests) == 1


async def test_missing_finish_at_output_limit_does_not_retry_malformed_portable_json():
    class Exhausted(Replies):
        async def aexecute_simple_task(self, *args, **kwargs):
            result = await super().aexecute_simple_task(*args, **kwargs)
            record_completion(
                {
                    "choices": [
                        {"finish_reason": None, "message": {"role": "assistant", "content": result}}
                    ],
                    "usage": {"completion_tokens": self.max_tokens},
                }
            )
            return result

    model = Exhausted(['{"requests":', "{}"])
    with pytest.raises(ValueError, match="exhausted its output budget"):
        await deliberate(model, steps=3, protocol="json")
    assert len(model.requests) == 1
