"""Notebook reads page canonical JSON without copying full documents into prompts."""

import json

import pytest

from backend.engine.chpm.notebook import NotebookError, NotebookWorkspace


def size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def test_default_pages_stay_bounded_and_reassemble_exact_canonical_json():
    raw = json.dumps({"thoughts": ['A "quoted" thought.\n' * 100, "雪" * 9000]}).encode()
    workspace = NotebookWorkspace(raw)
    offset, fragments = 0, []
    while True:
        result = workspace.read(offset=offset)
        assert size(result) <= 1400
        assert result["offset"] == offset and result["revision"] == 0
        fragments.append(result["json_fragment"])
        if result["complete"]:
            break
        assert result["next_offset"] > offset
        offset = result["next_offset"]
    assert "".join(fragments).encode() == workspace.canonical_bytes
    assert not workspace.changed


def test_read_limit_includes_escaped_fragment_and_metadata():
    workspace = NotebookWorkspace(json.dumps({"text": '\n\t\\"' * 10000}).encode(), revision=12)
    result = workspace.read("/text", limit=256)
    assert size(result) <= 256 and not result["complete"]
    assert result["type"] == "string" and result["total_chars"] > 10000


def test_huge_document_never_becomes_one_tool_result():
    workspace = NotebookWorkspace(('"' + "x" * 15_999_998 + '"').encode())
    result = workspace.read()
    assert size(result) <= 1400 and not result["complete"]
    assert result["total_chars"] == 16_000_000


@pytest.mark.parametrize(
    "kwargs",
    [
        {"offset": True},
        {"offset": -1},
        {"offset": 5},
        {"limit": True},
        {"limit": 255},
        {"limit": 4097},
    ],
)
def test_invalid_read_pagination_is_rejected(kwargs):
    workspace = NotebookWorkspace()
    with pytest.raises(NotebookError):
        workspace.read(**kwargs)
    assert workspace.canonical_bytes == b"{}"
