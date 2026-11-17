"""Combined argument faults need bounded, private-safe feedback within three rounds."""

import json
import traceback
from copy import deepcopy

import pytest

from backend.engine.chpm.errors import RecoverableChpmError
from backend.engine.chpm.native_tool_contracts import NativeToolArgumentError, parse_call
from backend.engine.chpm.notebook import NotebookWorkspace
from backend.engine.chpm.notebook_tools import NotebookDraft
from backend.engine.chpm.schema import Usage
from tests.test_chpm_native_notebook_loop import call, investigate, turn
from tests.test_chpm_three_round_recovery import investigate_at_budget


@pytest.mark.parametrize(
    ("name", "arguments", "fields"),
    [
        ("notebook_write", {}, ["path", "expected_revision", "value"]),
        ("notebook_write", {"expected_revision": "0"}, ["path", "expected_revision", "value"]),
        (
            "notebook_write",
            {"path": 5, "expected_revision": True, "value": None},
            ["path", "expected_revision"],
        ),
        ("notebook_read", {"path": 5, "offset": "0", "limit": True}, ["path", "offset", "limit"]),
        (
            "notebook_edit",
            {"expected_revision": False, "operations": [{"op": "add"}]},
            ["expected_revision", "operations[0].path", "operations[0].value"],
        ),
        (
            "notebook_edit",
            {
                "expected_revision": "0",
                "operations": [
                    {"op": "unknown", "path": "relative", "value": None},
                    {"op": "remove", "path": 5, "value": None},
                ],
            },
            [
                "expected_revision",
                "operations[0].op",
                "operations[0].path",
                "operations[1].path",
                "operations[1].value",
            ],
        ),
    ],
)
def test_one_feedback_result_reports_multiple_missing_or_invalid_declared_fields(
    name, arguments, fields
):
    with pytest.raises(NativeToolArgumentError) as error:
        parse_call(name, json.dumps(arguments))
    for field in fields:
        assert field in error.value.message
    assert len(error.value.message) <= 400
    if "expected_revision" in fields:
        assert "integer" in error.value.message


def test_aggregate_diagnostics_never_repeat_values_pointer_contents_or_unknown_keys():
    canary = "PRIVATE_ARGUMENT_AND_KEY_CANARY"
    with pytest.raises(NativeToolArgumentError) as error:
        parse_call(
            "notebook_write",
            json.dumps(
                {"path": canary, "expected_revision": canary, "value": canary, canary: True}
            ),
        )
    assert canary not in error.value.message
    assert "path" in error.value.message and "expected_revision" in error.value.message
    assert "unexpected" in error.value.message.casefold()
    assert len(error.value.message) <= 400
    assert canary not in "".join(traceback.format_exception(error.value))


def test_many_edit_faults_report_a_bounded_subset_and_explicitly_mark_omissions():
    with pytest.raises(NativeToolArgumentError) as error:
        parse_call(
            "notebook_edit",
            json.dumps({"expected_revision": False, "operations": [{"op": "add"}] * 16}),
        )
    assert "more" in error.value.message.casefold()
    assert all(
        field in error.value.message
        for field in ["expected_revision", "operations[0].path", "operations[0].value"]
    )
    assert len(error.value.message) <= 400


def test_unknown_tool_feedback_lists_only_static_allowed_names():
    with pytest.raises(NativeToolArgumentError) as error:
        parse_call("PRIVATE_UNKNOWN_NAME_CANARY", "{}")
    assert "PRIVATE_UNKNOWN_NAME_CANARY" not in error.value.message
    assert "notebook_read" in error.value.message and "search_memory" in error.value.message
    assert len(error.value.message) <= 400


class CorrectingModel:
    model = "offline-combined-errors"
    max_tokens = 1200
    request_timeout = 1

    def __init__(self, protocol, first_value=True):
        self.protocol, self.requests, self.feedback = protocol, [], []
        self.first_value = first_value
        self.sizes = []

    def response(self, results):
        if len(self.requests) == 1:
            return [
                (
                    "notebook_write",
                    {"path": "/must-not-run", "expected_revision": 0, "value": self.first_value},
                ),
                ("notebook_write", {"expected_revision": False}),
            ]
        self.feedback = results
        if len(self.requests) == 2:
            message = results[-1].get("message", "")
            if not all(
                field in message for field in ("path", "expected_revision", "value", "integer")
            ):
                return []
            return [
                ("notebook_write", {"path": "/reflection", "expected_revision": 0, "value": None})
            ]
        return [("notebook_read", {"path": "/reflection"})]

    async def aexecute_tool_turn(self, messages, tools, model, **kwargs):
        self.requests.append(deepcopy(messages))
        self.sizes.append(
            len(json.dumps({"messages": messages, "tools": tools}, ensure_ascii=False))
        )
        results = [json.loads(item["content"]) for item in messages if item["role"] == "tool"]
        return turn(
            *(
                call(f"round-{len(self.requests)}-{index}", name, arguments)
                for index, (name, arguments) in enumerate(self.response(results))
            )
        )

    async def aexecute_simple_task(self, system, content, model, **kwargs):
        payload = json.loads(content)
        self.requests.append(payload)
        self.sizes.append(len(system) + len(content))
        results = [item for batch in payload["previous_lookups"] for item in batch["results"]]
        return json.dumps(
            {
                "requests": [
                    {"name": name, "arguments": arguments}
                    for name, arguments in self.response(results)
                ]
            }
        )


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_combined_faults_can_be_corrected_once_then_read_without_executing_partial_batch(
    protocol,
):
    original = b'{"existing":"Keep this earlier thought."}'
    draft, model = NotebookDraft(NotebookWorkspace(original)), CorrectingModel(protocol)

    tools, audit, usage = await investigate(model, draft=draft, steps=3, protocol=protocol)

    assert len(model.requests) == usage.calls == 3
    assert [item["status"] for item in model.feedback[:2]] == [
        "batch_rejected",
        "invalid_arguments",
    ]
    assert [item["results"][-1]["status"] for item in audit] == ["invalid_arguments", "ok", "ok"]
    assert json.loads(draft.workspace.canonical_bytes) == {
        "existing": "Keep this earlier thought.",
        "reflection": None,
    }
    assert draft.workspace.revision == 1 and draft.committable
    assert tools.notebook.reads[-1]["json_fragment"] == "null"
    assert not tools.pins and not tools.beliefs


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_aggregated_feedback_cannot_bypass_8k_admission_or_publish_an_invalid_batch(protocol):
    original = b'{"existing":"Keep this earlier thought."}'
    draft, model, usage = (
        NotebookDraft(NotebookWorkspace(original)),
        # Keep the recovery over budget independently of instruction compression.
        CorrectingModel(protocol, first_value={"budget_padding": "x" * 4000}),
        Usage(),
    )

    with pytest.raises(RecoverableChpmError, match="input exceeds its configured size limit"):
        await investigate_at_budget(model, draft, protocol, 8000, usage)

    assert len(model.requests) == usage.calls == (0 if protocol == "native" else 1)
    assert all(size <= 8000 for size in model.sizes)
    assert usage.input_chars == sum(model.sizes)
    assert draft.workspace.canonical_bytes == original and draft.workspace.revision == 0
    assert not draft.committable and not draft.workspace.changed
