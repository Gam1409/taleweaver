"""Notebook documents are strict inert JSON with one exact canonical byte quota."""

import json
from copy import deepcopy

import pytest

from backend.engine.chpm.notebook import (
    MAX_BYTES,
    NotebookError,
    NotebookWorkspace,
    codec,
    decode,
    encode,
    preflight,
    tree,
)


def test_canonical_json_preserves_arbitrary_subjective_text_and_unicode():
    value = {"thoughts": "  I might be wrong.\n", "quotes": ["λ", "雪", "🙂"], "a": None}
    canonical = encode(value)
    assert (
        canonical
        == '{"a":null,"quotes":["λ","雪","🙂"],"thoughts":"  I might be wrong.\\n"}'.encode()
    )
    assert decode(canonical) == value
    assert encode(decode(canonical)) == canonical


@pytest.mark.parametrize("unit", ["x", "é", "🙂"])
def test_exact_canonical_utf8_quota_accepts_limit_and_rejects_one_byte_more(unit):
    count, remainder = divmod(MAX_BYTES - 2, len(unit.encode()))
    value = unit * count + "x" * remainder
    assert len(encode(value)) == MAX_BYTES
    with pytest.raises(NotebookError, match="16,000,000"):
        encode(value + "x")


@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), {1: "coerced key"}, ("tuple",), {"a": object()}, "\ud800"]
)
def test_non_json_python_values_are_rejected(value):
    with pytest.raises(NotebookError):
        encode(value)


@pytest.mark.parametrize(
    "raw",
    [
        '{"a":1,"a":2}',
        '{"nested":{"x":1,"x":2}}',
        "NaN",
        "Infinity",
        "1e999",
        '{"a":1,"\\u0061":2}',
        '"\\ud800"',
        b'"\xff"',
    ],
)
def test_raw_parser_rejects_duplicates_nonfinite_numbers_and_invalid_unicode(raw):
    with pytest.raises(NotebookError):
        decode(raw)


def test_cycles_and_custom_scalar_subclasses_are_not_json():
    value = []
    value.append(value)
    with pytest.raises(NotebookError):
        encode(value)

    class CustomInt(int):
        pass

    with pytest.raises(NotebookError):
        encode(CustomInt(1))


def test_pointer_escaping_missing_null_and_root_delete():
    workspace = NotebookWorkspace(b'{"":null,"a/b":{"~key":["first","second"]}}')
    assert workspace.read("/")["json_fragment"] == "null"
    assert workspace.read("/a~1b/~0key/1")["json_fragment"] == '"second"'
    workspace.write("/a~1b/~0key/1", '"changed"', expected_revision=0)
    assert workspace.read("/a~1b/~0key/1")["json_fragment"] == '"changed"'
    with pytest.raises(NotebookError) as error:
        workspace.read("/missing")
    assert error.value.code == "missing_path"
    workspace.delete("", expected_revision=1)
    assert workspace.canonical_bytes == b"{}"


@pytest.mark.parametrize(
    "pointer", ["relative", "/bad~", "/bad~2", "/items/01", "/items/-1", "/items/2"]
)
def test_invalid_pointer_or_array_index_does_not_mutate_document(pointer):
    workspace = NotebookWorkspace(b'{"items":[1]}')
    with pytest.raises(NotebookError):
        workspace.write(pointer, "2", expected_revision=0)
    assert workspace.canonical_bytes == b'{"items":[1]}' and workspace.revision == 0


def test_staged_writes_edits_and_deletes_see_previous_changes_and_preserve_inputs():
    workspace = NotebookWorkspace()
    workspace.write("/notes", '["one"]', expected_revision=0)
    operations = [
        {"op": "add", "path": "/notes/-", "value_json": '"two"'},
        {"op": "replace", "path": "/notes/0", "value_json": '"revised"'},
    ]
    before = deepcopy(operations)
    workspace.edit(operations, expected_revision=1)
    assert operations == before
    assert decode(workspace.canonical_bytes) == {"notes": ["revised", "two"]}
    workspace.delete("/notes/1", expected_revision=2)
    assert workspace.read("/notes")["json_fragment"] == '["revised"]'
    assert workspace.revision == 3 and workspace.changed


def test_multi_edit_is_atomic_when_a_later_operation_fails():
    workspace = NotebookWorkspace(b'{"notes":["kept"]}', revision=7)
    with pytest.raises(NotebookError):
        workspace.edit(
            [
                {"op": "replace", "path": "/notes/0", "value_json": '"discarded"'},
                {"op": "remove", "path": "/absent"},
            ],
            expected_revision=7,
        )
    assert workspace.canonical_bytes == b'{"notes":["kept"]}' and workspace.revision == 7


def test_patch_test_failure_and_quota_failure_leave_staged_document_unchanged():
    workspace = NotebookWorkspace(b'{"kept":true}')
    with pytest.raises(NotebookError):
        workspace.edit(
            [
                {"op": "add", "path": "/draft", "value_json": "1"},
                {"op": "test", "path": "/kept", "value_json": "1"},
            ],
            expected_revision=0,
        )
    with pytest.raises(NotebookError):
        workspace.write("/too_large", json.dumps("x" * MAX_BYTES), expected_revision=0)
    assert workspace.canonical_bytes == b'{"kept":true}' and workspace.revision == 0


def test_quota_checks_complete_document_even_when_fragment_itself_fits():
    workspace = NotebookWorkspace(b'{"kept":1}')
    fragment = '"' + "x" * (MAX_BYTES - 2) + '"'
    assert len(fragment.encode()) == MAX_BYTES
    with pytest.raises(NotebookError) as error:
        workspace.write("/extra", fragment, expected_revision=0)
    assert error.value.code == "quota_exceeded"
    assert workspace.canonical_bytes == b'{"kept":1}' and workspace.revision == 0


def test_copy_on_write_shares_untouched_branches_and_preserves_original_tree():
    original = {"left": {"note": "original"}, "right": ["preserved"]}
    changed = tree.change(original, "/left/note", "replace", "revised")
    assert original == {"left": {"note": "original"}, "right": ["preserved"]}
    assert changed["left"] is not original["left"]
    assert changed["right"] is original["right"]


def test_root_values_and_array_patch_insertions_have_explicit_semantics():
    workspace = NotebookWorkspace(b"null")
    workspace.write("", "[1,3]", expected_revision=0)
    workspace.edit(
        [
            {"op": "add", "path": "/1", "value_json": "2"},
            {"op": "test", "path": "/0", "value_json": "1.0"},
        ],
        expected_revision=1,
    )
    assert workspace.canonical_bytes == b"[1,2,3]"
    workspace.write("/1", "4", expected_revision=2)
    workspace.write("/-", "5", expected_revision=3)
    assert workspace.canonical_bytes == b"[1,4,3,5]"


@pytest.mark.parametrize("revision", [True, False, 0.0, "0", None, -1, 1])
def test_expected_revision_is_a_strict_matching_nonnegative_integer(revision):
    workspace = NotebookWorkspace()
    with pytest.raises(NotebookError):
        workspace.write("/note", '"draft"', expected_revision=revision)
    assert workspace.canonical_bytes == b"{}" and workspace.revision == 0


def test_unchanged_write_does_not_bump_revision_and_restoring_base_clears_changed():
    workspace = NotebookWorkspace(b'{"note":"kept"}', revision=4)
    assert workspace.write("/note", '"kept"', expected_revision=4)["changed"] is False
    workspace.write("/note", '"new"', expected_revision=4)
    workspace.write("/note", '"kept"', expected_revision=5)
    assert workspace.revision == 6 and not workspace.changed
    assert workspace.base_revision == 4
    with pytest.raises(AttributeError):
        workspace.base_revision = 7


def test_code_and_path_strings_remain_inert_notebook_data(tmp_path):
    destination = tmp_path / "must_not_exist"
    text = f"__import__('pathlib').Path({str(destination)!r}).write_text('executed')"
    workspace = NotebookWorkspace()
    workspace.write("/..", "{}", expected_revision=0)
    workspace.write("/../~0state", json.dumps(text), expected_revision=1)
    assert json.loads(workspace.read("/../~0state")["json_fragment"]) == text
    assert not destination.exists()


def test_archive_preflight_allows_only_explicit_bounded_envelope_structure(monkeypatch):
    monkeypatch.setattr(codec, "MAX_DEPTH", 2)
    monkeypatch.setattr(codec, "MAX_NODES", 4)
    raw = '[{"document":[[null]]}]'
    with pytest.raises(NotebookError, match="technical JSON"):
        preflight(raw)
    assert preflight(raw, extra_depth=2, extra_nodes=3, max_transport_bytes=100) == raw
    assert decode("[[null]]") == [[None]]


@pytest.mark.parametrize("raw", ['"雪"', '"雪"'.encode()])
def test_preflight_transport_quota_counts_utf8_bytes(raw):
    assert preflight(raw, max_transport_bytes=5) == '"雪"'
    with pytest.raises(NotebookError, match="transport"):
        preflight(raw, max_transport_bytes=4)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"extra_depth": True},
        {"extra_depth": 9},
        {"extra_nodes": -1},
        {"extra_nodes": 257},
        {"max_transport_bytes": True},
        {"max_transport_bytes": 0},
    ],
)
def test_preflight_rejects_invalid_or_unbounded_host_allowances(kwargs):
    with pytest.raises(NotebookError):
        preflight(b"{}", **kwargs)


def test_public_preflight_validates_unicode_but_leaves_syntax_to_strict_parser():
    with pytest.raises(NotebookError):
        preflight('"\ud800"')
    with pytest.raises(NotebookError):
        preflight(b'"\xff"')
    assert preflight('{"unfinished":') == '{"unfinished":'
    with pytest.raises(NotebookError):
        decode('{"unfinished":')
