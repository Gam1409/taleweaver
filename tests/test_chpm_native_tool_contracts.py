"""Native tool arguments stay strict while notebook values remain arbitrary JSON."""

import json

import pytest
from jsonschema import Draft202012Validator

from backend.engine.chpm.agent_contracts import Lookup
from backend.engine.chpm.native_tool_contracts import (
    NativeToolArgumentError,
    canonical_tool_name,
    known_tool_names,
    parse_call,
    tool_definitions,
)
from backend.engine.chpm.notebook import MAX_BYTES, NotebookWorkspace, decode
from backend.engine.chpm.notebook_requests import NotebookEdit, NotebookRead, NotebookWrite
from backend.engine.chpm.notebook_tools import NotebookDraft


def definition(name):
    return next(tool["function"] for tool in tool_definitions() if tool["function"]["name"] == name)


def write(value, **arguments):
    return parse_call(
        "notebook_write",
        json.dumps(
            {"path": "", "expected_revision": 0, "value": value, **arguments}, ensure_ascii=False
        ),
    )


def test_native_functions_are_distinct_and_only_notebook_tools_are_optional():
    tools = tool_definitions()
    names = [tool["function"]["name"] for tool in tools]
    assert len(names) == len(set(names)) == 11
    assert {tool["function"]["name"] for tool in tool_definitions(False)} == {
        "search_memory",
        "read_memory",
        "inspect_self",
        "visible_clothing",
        "inspect_beliefs",
        "read_belief_basis",
    }
    for tool in tools:
        function = tool["function"]
        assert function["strict"] is False
        assert function["parameters"]["additionalProperties"] is False
        assert "tool" not in function["parameters"]["properties"]
        Draft202012Validator.check_schema(function["parameters"])


def test_canonical_tool_metadata_uses_only_the_immutable_capability_allowlist():
    names = known_tool_names()
    assert isinstance(names, frozenset)
    assert names == {tool["function"]["name"] for tool in tool_definitions()}
    assert {canonical_tool_name(name) for name in names} == names


@pytest.mark.parametrize(
    "name", ["PRIVATE_NOTE_CANARY", "\ud800", "unknown_tool", "", None, [], {}]
)
def test_unknown_tool_names_cannot_copy_private_text_into_metadata(name):
    assert canonical_tool_name(name) == "unknown_tool"


@pytest.mark.parametrize(
    "name",
    [
        "inspect_self",
        "notebook_info",
        "notebook_read",
        "search_memory",
        "read_memory",
        "visible_clothing",
        "inspect_beliefs",
        "read_belief_basis",
    ],
)
def test_read_only_native_functions_have_no_mutation_revision(name):
    assert "expected_revision" not in definition(name)["parameters"]["properties"]
    arguments = {"expected_revision": 0}
    if "argument" in definition(name)["parameters"]["properties"]:
        arguments["argument"] = "known"
    with pytest.raises(NativeToolArgumentError):
        parse_call(name, json.dumps(arguments))


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        0,
        -3.5,
        [],
        [None, "雪", {"free": "keys"}],
        {},
        {"npc_id": "a literal note key", "tool": "also data", "__class__": {"arbitrary": [1, 2]}},
    ],
)
def test_native_values_preserve_every_json_root_type_and_freely_chosen_keys(value):
    request = write(value)
    assert isinstance(request, NotebookWrite) and decode(request.value_json) == value
    assert Draft202012Validator(definition("notebook_write")["parameters"]).is_valid(
        {"path": "", "expected_revision": 0, "value": value}
    )
    draft = NotebookDraft(NotebookWorkspace())
    assert draft.execute(request)["status"] == "ok"
    assert decode(draft.workspace.canonical_bytes) == value


def test_native_text_quotes_unicode_and_pointer_whitespace_survive_exactly():
    value = {"  key/with~escapes  ": "  'quoted' \"text\"\n雪 🙂 \\  "}
    request = write(value)
    assert decode(request.value_json) == value
    read = parse_call("notebook_read", '{"path":"/  key~1with~0escapes  "}')
    assert isinstance(read, NotebookRead) and read.path == "/  key~1with~0escapes  "
    draft = NotebookDraft(NotebookWorkspace())
    draft.execute(request)
    assert json.loads(draft.execute(read)["json_fragment"]) == value["  key/with~escapes  "]
    assert json.loads(write("🙂").value_json) == json.loads(
        parse_call(
            "notebook_write", '{"path":"","expected_revision":0,"value":"\\ud83d\\ude42"}'
        ).value_json
    )


@pytest.mark.parametrize(
    "raw",
    [
        '{"expected_revision":0,"expected_revision":1,"value":null}',
        '{"expected_revision":0,"value":{"a":1,"\\u0061":2}}',
        '{"expected_revision":0,"value":NaN}',
        '{"expected_revision":0,"value":Infinity}',
        '{"expected_revision":0,"value":-Infinity}',
        '{"expected_revision":0,"value":1e999}',
        '{"expected_revision":0,"value":"\\ud800"}',
        '{"expected_revision":0,"value":{"\\udfff":1}}',
        '{"expected_revision":0,"value":',
        '```json\n{"value":1}\n```',
        "[]",
        "null",
    ],
)
def test_malformed_duplicate_nonfinite_and_invalid_unicode_arguments_are_rejected(raw):
    with pytest.raises(NativeToolArgumentError):
        parse_call("notebook_write", raw)


@pytest.mark.parametrize("revision", [True, False, 0.0, "0", None, -1])
def test_native_mutation_revision_keeps_strict_integer_semantics(revision):
    with pytest.raises(NativeToolArgumentError):
        write(None, expected_revision=revision)


@pytest.mark.parametrize(
    "field",
    ["owner_id", "session_id", "npc_id", "actor_id", "branch_id", "filename", "tool", "value_json"],
)
def test_native_argument_envelopes_reject_scope_selectors_and_legacy_wrappers(field):
    with pytest.raises(NativeToolArgumentError):
        write({}, **{field: "PRIVATE_ARGUMENT_CANARY"})


@pytest.mark.parametrize("name", ["unknown", "exec", "__class__", "", None, []])
def test_unknown_native_names_do_not_resolve_attributes_or_functions(name):
    with pytest.raises(NativeToolArgumentError):
        parse_call(name, "{}")


def test_all_legacy_lookup_functions_return_the_existing_request_model():
    assert parse_call("inspect_self", "{}") == Lookup(tool="inspect_self")
    for name in (
        "search_memory",
        "read_memory",
        "visible_clothing",
        "inspect_beliefs",
        "read_belief_basis",
    ):
        assert parse_call(name, '{"argument":"known"}') == Lookup(tool=name, argument="known")
    with pytest.raises(NativeToolArgumentError):
        parse_call("inspect_self", '{"argument":""}')


def test_edit_values_are_typed_json_and_null_is_distinct_from_missing():
    operations = [
        {"op": "add", "path": "/null", "value": None},
        {"op": "test", "path": "/null", "value": None},
        {"op": "replace", "path": "/null", "value": ["updated"]},
        {"op": "remove", "path": "/null"},
    ]
    body = {"expected_revision": 0, "operations": operations}
    request = parse_call("notebook_edit", json.dumps(body))
    assert isinstance(request, NotebookEdit)
    assert request.operations[0].value_json == "null" and request.operations[-1].value_json is None
    assert Draft202012Validator(definition("notebook_edit")["parameters"]).is_valid(body)
    workspace = NotebookWorkspace()
    assert NotebookDraft(workspace).execute(request)["status"] == "ok"
    assert workspace.canonical_bytes == b"{}" and workspace.revision == 0


@pytest.mark.parametrize(
    "operation",
    [
        {"op": "add", "path": "/x"},
        {"op": "remove", "path": "/x", "value": None},
        {"op": "replace", "path": "/x", "value_json": "null"},
        {"op": [], "path": "/x", "value": 1},
        {"op": "add", "path": "/x", "value": 1, "npc_id": "other"},
        {"op": "add", "path": "relative", "value": 1},
    ],
)
def test_every_edit_operation_is_validated_before_the_request_is_returned(operation):
    with pytest.raises(NativeToolArgumentError):
        parse_call(
            "notebook_edit",
            json.dumps(
                {
                    "expected_revision": 0,
                    "operations": [{"op": "add", "path": "/valid", "value": True}, operation],
                }
            ),
        )


def test_native_value_and_operation_limits_match_existing_transport_contracts():
    assert len(write("x" * 8190).value_json) == 8192
    assert len(write("🙂" * 8190).value_json) == 8192
    with pytest.raises(NativeToolArgumentError, match="8192"):
        write("x" * 8191)
    operations = [{"op": "add", "path": f"/{number}", "value": None} for number in range(16)]
    assert (
        len(
            parse_call(
                "notebook_edit", json.dumps({"expected_revision": 0, "operations": operations})
            ).operations
        )
        == 16
    )
    for invalid in ([], [*operations, operations[0]]):
        with pytest.raises(NativeToolArgumentError, match="1 to 16"):
            parse_call("notebook_edit", json.dumps({"expected_revision": 0, "operations": invalid}))


def test_small_native_mutations_preserve_the_full_document_byte_quota():
    envelope = b'{"bulk":"","flag":false}'
    workspace = NotebookWorkspace(
        b'{"bulk":"' + b"x" * (MAX_BYTES - len(envelope)) + b'","flag":false}'
    )
    assert workspace.byte_size == MAX_BYTES
    result = NotebookDraft(workspace).execute(write(True, path="/flag"))
    assert result["status"] == "ok" and workspace.byte_size == MAX_BYTES - 1


def test_native_error_feedback_is_bounded_and_omits_private_contents():
    canary = "PRIVATE_VALUE_CANARY"
    bodies = [
        '{"expected_revision":true,"value":"' + canary + '"}',
        '{"expected_revision":0,"value":{"' + canary + '":1,"' + canary + '":2}}',
        '{"expected_revision":0,"value":null,"' + canary + '":1}',
    ]
    for body in bodies:
        with pytest.raises(NativeToolArgumentError) as error:
            parse_call("notebook_write", body)
        assert canary not in str(error.value) and len(str(error.value)) <= 400
        assert error.value.code and error.value.message == str(error.value)


def test_native_code_like_values_remain_inert_data(tmp_path):
    destination = tmp_path / "never-created"
    value = {
        "__class__": f"__import__('pathlib').Path({str(destination)!r}).write_text('executed')"
    }
    draft = NotebookDraft(NotebookWorkspace())
    assert draft.execute(write(value))["status"] == "ok"
    assert decode(draft.workspace.canonical_bytes) == value and not destination.exists()
