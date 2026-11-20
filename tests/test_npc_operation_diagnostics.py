"""Typed refusals retain full owner diagnostics only in the existing host trace."""

from contextlib import contextmanager
from dataclasses import replace

import pytest

from backend.core.state_rejection_trace import scope
from backend.core.system_diagnostics import service
from backend.engine import turn_controls
from backend.engine.chpm import tool_operations
from backend.engine.chpm.notebook_tools import result_summary
from backend.engine.npc_actions import control
from backend.engine.npc_actions.contracts import Take
from backend.engine.visual_novel.item_rejections import current_rejection, remember
from tests.state_trace_support import (
    event_payloads,
    isolate_trace_directory,
    trace_files,
    trace_rows,
)
from tests.test_npc_action_previews import fixture
from tests.test_npc_attempt_operations import host


def test_generic_owner_refusal_preserves_sanitized_trace_without_copying_diagnostic_into_model(
    monkeypatch, tmp_path
):
    manager = host()
    _, _, draft = fixture()
    draft.scope = replace(draft.scope, control=turn_controls.scope(manager, "npc_command_preview"))
    detail = "A canonical owner constraint could not be satisfied. " * 150
    error = ValueError(detail + "Bearer diagnostic-placeholder-secret")

    def invalid(_request):
        raise error

    monkeypatch.setattr(draft, "_preview", invalid)
    with contextmanager(isolate_trace_directory)(tmp_path, monkeypatch):
        service.set_enabled(True, state_failure_traces=True)
        with scope(session_id=manager.game_id, turn_id="transport", operation="turn"):
            result = draft.execute(Take(tool="take_item", item_id="KEY"))
        assert result["status"] == "blocked" and result["reason_code"] == "owner_rejected"
        assert result["message"] == control.MESSAGES["owner_rejected"]
        assert result["diagnostic_error_type"] == "ValueError"
        assert result["diagnostic_detail"] == detail[:4096]
        assert result_summary(result)["diagnostic_detail"] == result["diagnostic_detail"]
        projected = tool_operations.for_model("take_item", result)
        assert not any(key.startswith("diagnostic_") for key in projected)
        assert projected["operation_id"] == result["operation_id"]
        assert detail not in str(projected)
        rejected = event_payloads(trace_rows(), "state.rejected")
        assert len(rejected) == 1
        traced = rejected[0]
        assert traced["reason_code"] == "npc_actions.owner_rejected"
        assert traced["details"]["diagnostic_detail"] == detail + "Bearer [credential excluded]"
        assert traced["details"]["operation"]["attempt_id"] == result["attempt_id"]
        assert traced["details"]["operation"]["operation_id"] == result["operation_id"]


def test_old_captured_denial_cannot_enter_the_new_attempt_or_its_trace(monkeypatch, tmp_path):
    manager = host()
    captured = turn_controls.scope(manager, "preliminary_items")
    turn_controls.close(manager)
    turn_controls.begin(manager)
    current = turn_controls.scope(manager, "preliminary_items")
    remember(manager, ValueError("A current owner diagnostic."), captured=current)
    denial = current_rejection(manager)
    with contextmanager(isolate_trace_directory)(tmp_path, monkeypatch):
        service.set_enabled(True, state_failure_traces=True)
        with (
            scope(session_id=manager.game_id, turn_id="new-transport", operation="turn"),
            pytest.raises(control.CommandRejectedError),
        ):
            remember(manager, ValueError("An obsolete owner diagnostic."), captured=captured)
        assert not trace_files()
    assert current_rejection(manager) == denial
    assert denial["attempt_id"] == current["attempt_id"] != captured["attempt_id"]
