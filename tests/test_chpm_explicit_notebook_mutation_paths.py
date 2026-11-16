"""Omitted mutation paths cannot accidentally replace or clear existing private notes."""

import json

import pytest
from jsonschema import Draft202012Validator

from backend.engine.chpm.native_tool_contracts import (
    NativeToolArgumentError,
    parse_call,
    tool_definitions,
)
from backend.engine.chpm.notebook import NotebookWorkspace
from backend.engine.chpm.notebook_requests import NotebookDelete, NotebookRead, NotebookWrite
from backend.engine.chpm.notebook_tools import NotebookDraft
from tests.test_chpm_json_tool_port import TextModel
from tests.test_chpm_native_notebook_loop import NativeModel, call, investigate, turn
from tests.test_chpm_three_round_recovery import (
    context_for,
    correlated_results,
    prior_calls,
)
from tests.test_chpm_three_round_recovery import (
    model_for as compatibility_model_for,
)

ORIGINAL = b'{"cabinet":{"reminder":"Check the hinge before opening."}}'
VALUE = {"qualification": "A private possibility, not an established fact."}


def model_for(protocol, batches):
    if protocol == "json":
        return compatibility_model_for(protocol, batches)
    return NativeModel(
        [
            turn(
                *(
                    call(f"round-{index}-call-{position}", name, arguments)
                    for position, (name, arguments) in enumerate(batch)
                )
            )
            for index, batch in enumerate(batches)
        ]
    )


def parameters(name):
    return next(
        tool["function"]["parameters"]
        for tool in tool_definitions()
        if tool["function"]["name"] == name
    )


def arguments(name, **extra):
    body = {"expected_revision": 4, **extra}
    if name == "notebook_write":
        body["value"] = VALUE
    return body


@pytest.mark.parametrize("name", ["notebook_write", "notebook_delete"])
def test_mutation_schema_requires_explicit_path_and_has_no_implicit_root_default(name):
    schema = parameters(name)
    assert "path" in schema["required"]
    assert "default" not in schema["properties"]["path"]
    validator = Draft202012Validator(schema)
    assert not validator.is_valid(arguments(name))
    assert validator.is_valid(arguments(name, path=""))
    assert validator.is_valid(arguments(name, path="/qualification"))


@pytest.mark.parametrize("name", ["notebook_write", "notebook_delete"])
def test_missing_mutation_path_has_bounded_correctable_feedback_and_never_changes_notes(name):
    draft = NotebookDraft(NotebookWorkspace(ORIGINAL, revision=4))
    with pytest.raises(NativeToolArgumentError) as error:
        draft.execute(parse_call(name, json.dumps(arguments(name))))

    assert error.value.code == "invalid_arguments"
    assert "path" in error.value.message and "''" in error.value.message
    assert VALUE["qualification"] not in error.value.message
    assert len(error.value.message) <= 400
    assert draft.workspace.canonical_bytes == ORIGINAL and draft.workspace.revision == 4


@pytest.mark.parametrize("protocol", ["native", "json"])
@pytest.mark.parametrize("name", ["notebook_write", "notebook_delete"])
async def test_omitted_path_rejects_the_entire_batch_before_an_earlier_valid_write(protocol, name):
    model = model_for(
        protocol,
        [
            [
                ("notebook_write", {"path": "/new", "value": True, "expected_revision": 4}),
                (name, arguments(name, expected_revision=5)),
            ],
            [],
        ],
    )
    draft = NotebookDraft(NotebookWorkspace(ORIGINAL, revision=4))

    _, audit, usage = await investigate(model, draft=draft, protocol=protocol)

    context = context_for(model, protocol, 1)
    feedback = correlated_results(context)
    assert [identifier for identifier, _ in feedback] == [
        item["id"] for item in prior_calls(context)
    ]
    assert [result["status"] for _, result in feedback] == ["batch_rejected", "invalid_arguments"]
    assert "path" in feedback[1][1]["message"]
    assert draft.workspace.canonical_bytes == ORIGINAL and draft.workspace.revision == 4
    assert not draft.workspace.changed
    assert usage.calls == 2 and audit[-1]["stop"] == "ready"


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_a_missing_write_path_can_be_corrected_without_replacing_unrelated_notes(protocol):
    model = model_for(
        protocol,
        [
            [("notebook_write", arguments("notebook_write"))],
            [("notebook_write", arguments("notebook_write", path="/qualification"))],
            [("notebook_read", {"path": "/qualification"})],
        ],
    )
    draft = NotebookDraft(NotebookWorkspace(ORIGINAL, revision=4))

    _, audit, usage = await investigate(model, draft=draft, protocol=protocol, steps=3)

    context = context_for(model, protocol, 1)
    assert context["personal_notebook"]["revision"] == 4
    assert correlated_results(context)[0][1]["status"] == "invalid_arguments"
    assert "path" in correlated_results(context)[0][1]["message"]
    expected = {**json.loads(ORIGINAL), "qualification": VALUE}
    assert json.loads(draft.workspace.canonical_bytes) == expected
    assert json.loads(draft.reads[-1]["json_fragment"]) == VALUE
    assert draft.workspace.revision == 5 and draft.committable
    assert usage.calls == 3 and audit[-1]["stop"] == "step_limit"


@pytest.mark.parametrize("value", [None, [], ["any", {"freely_chosen": True}], "plain text", VALUE])
def test_explicit_empty_path_still_intentionally_replaces_the_root_with_arbitrary_json(value):
    draft = NotebookDraft(NotebookWorkspace(ORIGINAL, revision=4))
    request = parse_call(
        "notebook_write", json.dumps({"path": "", "expected_revision": 4, "value": value})
    )

    assert draft.execute(request)["status"] == "ok"
    assert json.loads(draft.workspace.canonical_bytes) == value
    assert draft.workspace.revision == 5


def test_explicit_empty_delete_path_still_intentionally_clears_the_root():
    draft = NotebookDraft(NotebookWorkspace(ORIGINAL, revision=4))
    request = parse_call("notebook_delete", '{"path":"","expected_revision":4}')

    assert draft.execute(request)["status"] == "ok"
    assert draft.workspace.canonical_bytes == b"{}" and draft.workspace.revision == 5


def test_read_default_and_legacy_typed_request_shapes_remain_compatible():
    request = parse_call("notebook_read", "{}")
    assert isinstance(request, NotebookRead) and request.path == ""
    assert "path" not in parameters("notebook_read")["required"]
    assert parameters("notebook_read")["properties"]["path"]["default"] == ""
    assert NotebookWrite(tool="notebook_write", expected_revision=0, value_json="null").path == ""
    assert NotebookDelete(tool="notebook_delete", expected_revision=0).path == ""


@pytest.mark.parametrize("explicit", [False, True])
async def test_legacy_wire_adapter_requires_intentional_root_path_at_the_shared_execution_boundary(
    explicit,
):
    request = {"tool": "notebook_write", "expected_revision": 4, "value_json": json.dumps(VALUE)}
    if explicit:
        request["path"] = ""
    model = TextModel([json.dumps({"requests": [request]}), '{"requests":[]}'])
    draft = NotebookDraft(NotebookWorkspace(ORIGINAL, revision=4))

    await investigate(model, draft=draft, protocol="json")

    status = correlated_results(context_for(model, "json", 1))[0][1]["status"]
    assert status == ("ok" if explicit else "invalid_arguments")
    assert json.loads(draft.workspace.canonical_bytes) == (
        VALUE if explicit else json.loads(ORIGINAL)
    )
