"""NPC-chosen notebook operations stay scoped, bounded, staged and private."""

import json

import pytest
from pydantic import ValidationError

from backend.engine.chpm.agent_contracts import INSTRUCTIONS, Lookup, NotebookStep, Step
from backend.engine.chpm.notebook.workspace import NotebookWorkspace
from backend.engine.chpm.notebook_requests import NotebookInfo, NotebookRead, NotebookWrite
from backend.engine.chpm.notebook_tools import NotebookDraft, request_summary, result_summary


def test_model_can_choose_write_then_read_in_one_existing_tool_round():
    plan = NotebookStep.model_validate(
        {
            "requests": [
                {
                    "tool": "notebook_write",
                    "path": "/note",
                    "value_json": '"Check the bridge tomorrow."',
                    "expected_revision": 0,
                },
                {"tool": "notebook_read", "path": "/note"},
            ]
        }
    )
    draft = NotebookDraft(NotebookWorkspace())
    written, read = [draft.execute(request) for request in plan.requests]
    assert written["changed"] and written["revision"] == 1
    assert json.loads(read["json_fragment"]) == "Check the bridge tomorrow."
    assert draft.workspace.canonical_bytes == b'{"note":"Check the bridge tomorrow."}'
    assert draft.context()["meaning"] == "self_authored_subjective_notes_not_world_evidence"


def test_model_tool_schema_has_no_caller_selected_notebook_identity():
    for selector in ("npc_id", "session_id", "owner_id", "filename", "branch_id"):
        with pytest.raises(ValidationError):
            NotebookStep.model_validate(
                {"requests": [{"tool": "notebook_read", selector: "another"}]}
            )


def test_duplicate_keys_and_stale_edit_keep_the_current_document():
    draft = NotebookDraft(NotebookWorkspace(b'{"note":"Keep this."}'))
    before = draft.workspace.canonical_bytes
    for value, revision in (('{"x":1,"x":2}', 0), ('"Replacement"', 7)):
        result = draft.execute(
            NotebookWrite(
                tool="notebook_write", path="", value_json=value, expected_revision=revision
            )
        )
        assert result["status"] != "ok"
        assert draft.workspace.canonical_bytes == before and draft.workspace.revision == 0


def test_personal_notebook_audits_do_not_copy_private_contents():
    draft = NotebookDraft(NotebookWorkspace())
    request = NotebookWrite(
        tool="notebook_write",
        path="/note",
        value_json='"PRIVATE_NOTE_CONTENT"',
        expected_revision=0,
    )
    written = draft.execute(request)
    read = draft.execute(NotebookRead(tool="notebook_read", path="/note"))
    trace = json.dumps([request_summary(request), result_summary(written), result_summary(read)])
    assert "PRIVATE_NOTE_CONTENT" not in trace and "value_json" not in trace
    assert "json_fragment" not in trace
    assert "PRIVATE_NOTE_CONTENT" in str(draft.context()["selected_reads"])
    search = Lookup(tool="search_memory", argument="PRIVATE_NOTE_CONTENT")
    assert "PRIVATE_NOTE_CONTENT" not in json.dumps(request_summary(search))


def test_metadata_only_exposes_this_current_documents_quota():
    draft = NotebookDraft(NotebookWorkspace())
    info = draft.execute(NotebookInfo(tool="notebook_info"))
    assert info["limit_bytes"] == 16_000_000 and info["used_bytes"] == 2
    assert info["remaining_bytes"] == 15_999_998 and draft.reads == []


def test_current_document_counter_is_not_a_history_of_notebooks():
    draft = NotebookDraft(NotebookWorkspace())
    for counter in range(3):
        draft.execute(
            NotebookWrite(tool="notebook_write", value_json=str(counter), expected_revision=counter)
        )
    assert draft.workspace.canonical_bytes == b"2" and draft.workspace.base_revision == 0
    assert draft.workspace.revision == 3 and "history" not in draft.context()


def test_disabled_notebook_uses_the_unchanged_read_only_contract():
    assert "notebook_" not in json.dumps(Step.model_json_schema())
    assert "notebook_" not in INSTRUCTIONS
    with pytest.raises(ValidationError):
        Step.model_validate({"requests": [{"tool": "notebook_info"}]})
