"""Explicit streamed failure contracts retain evidence after caught host errors."""

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.core.system_diagnostics import service
from backend.engine.visual_novel.concurrency import guard_session_turn
from tests.state_trace_support import (
    event_payloads,
    isolate_trace_directory,
    trace_files,
    trace_rows,
)


@pytest.fixture(autouse=True)
def isolated_diagnostics(tmp_path, monkeypatch):
    yield from isolate_trace_directory(tmp_path, monkeypatch)


async def stream_frame(event, payload, *, caught_error=False):
    frame = f"event: {event}\ndata: {json.dumps(payload)}\n\n"
    manager = SimpleNamespace(
        game_id=str(uuid4()), turn_id=str(uuid4()), state=SimpleNamespace(inventory=[])
    )

    @guard_session_turn
    async def process(owner, user_msg):
        service.detail("detail.llm.request", messages=[{"role": "user", "content": user_msg}])
        if caught_error:
            try:
                raise RuntimeError("Synthetic caught pipeline failure")
            except RuntimeError:
                yield frame
                return
        yield frame

    result = [chunk async for chunk in process(manager, "Neutral player action")]
    assert result == [frame]
    assert manager.state.inventory == []
    return frame


async def test_caught_pipeline_error_event_still_marks_rejected_turn():
    service.set_enabled(True, state_failure_traces=True)
    payload = {"detail": "Synthetic caught pipeline failure", "retryable": True}
    await stream_frame("error", payload, caught_error=True)
    assert len(trace_files()) == 1
    reason = event_payloads(trace_rows(), "state.rejected")[0]
    assert reason["domain"] == "turn"
    assert reason["reason_code"] == "engine_error_event"
    assert reason["details"]["event_payload"] == payload
    assert event_payloads(trace_rows(), "detail.llm.request")


async def test_explicit_partial_final_marks_unconfirmed_narration_without_changing_output():
    service.set_enabled(True, state_failure_traces=True)
    payload = {"narration_incomplete": True, "content": "Neutral partial narration"}
    await stream_frame("final", payload)
    reason = event_payloads(trace_rows(), "state.rejected")[0]
    assert reason["reason_code"] == "narration_incomplete"
    assert reason["details"]["event_payload"] == payload


@pytest.mark.parametrize("value", [False, None, 0, 1, "true"])
async def test_final_without_exact_incomplete_flag_is_not_a_rejection(value):
    service.set_enabled(True, state_failure_traces=True)
    await stream_frame(
        "final",
        {
            "narration_incomplete": value,
            "content": "Words such as error or incomplete are ordinary narration.",
        },
    )
    assert trace_files() == []


async def test_nonfinal_payload_and_disabled_capture_do_not_create_failure_packets():
    service.set_enabled(True, state_failure_traces=True)
    await stream_frame("message", {"narration_incomplete": True})
    assert trace_files() == []
    service.set_enabled(True)
    await stream_frame("error", {"detail": "Capture is off"}, caught_error=True)
    assert trace_files() == []
