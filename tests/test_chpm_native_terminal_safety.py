"""Rejected completion states and repeated calls cannot commit staged notes."""

import pytest

from tests.test_chpm_native_notebook_loop import NativeModel, call, investigate, turn


@pytest.mark.parametrize("reason", ["content_filter", "unknown_terminal", {"invalid": "reason"}])
async def test_rejected_terminal_reasons_never_execute_or_retry(reason):
    model = NativeModel(
        [
            turn(
                call(
                    "rejected", "notebook_write", {"value": {"bad": True}, "expected_revision": 0}
                ),
                finish_reason=reason,
            )
        ]
    )
    tools, audit, usage = await investigate(model)

    assert len(model.requests) == usage.calls == 1
    assert tools.notebook.workspace.canonical_bytes == b"{}"
    assert not tools.notebook.committable
    assert audit[-1]["stop"] == "invalid_plan"


@pytest.mark.parametrize("reason", ["content_filter", "unknown_terminal"])
async def test_a_rejected_second_response_invalidates_earlier_staging(reason):
    model = NativeModel(
        [
            turn(
                call(
                    "first",
                    "notebook_write",
                    {"path": "/first", "value": 1, "expected_revision": 0},
                )
            ),
            turn(
                call(
                    "second",
                    "notebook_write",
                    {"path": "/second", "value": 2, "expected_revision": 1},
                ),
                finish_reason=reason,
            ),
        ]
    )
    tools, audit, usage = await investigate(model)

    assert len(model.requests) == usage.calls == 2
    assert tools.notebook.workspace.canonical_bytes == b'{"first":1}'
    assert not tools.notebook.committable
    assert not tools.notebook.context()["updates_committable"]
    assert audit[-1]["stop"] == "invalid_plan"


async def test_a_call_id_cannot_be_reused_with_different_arguments_in_a_later_round():
    model = NativeModel(
        [
            turn(
                call(
                    "same", "notebook_write", {"path": "/first", "value": 1, "expected_revision": 0}
                )
            ),
            turn(
                call(
                    "same",
                    "notebook_write",
                    {"path": "/second", "value": 2, "expected_revision": 1},
                )
            ),
        ]
    )
    tools, audit, usage = await investigate(model)

    assert len(model.requests) == usage.calls == 2
    assert tools.notebook.workspace.canonical_bytes == b'{"first":1}'
    assert not tools.notebook.committable
    assert audit[-1]["stop"] == "invalid_plan"
    assert tools.notebook.context()["tool_feedback"][-1]["status"] == "invalid_call_envelope"
