"""Independent failed checks have self-contained packets without unrelated step snapshots."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.core.engine_detailed_trace import step, turn_context
from backend.core.state_rejection_trace import reject
from backend.core.system_diagnostics import service
from tests.state_trace_support import (
    event_payloads,
    isolate_trace_directory,
    trace_files,
    trace_rows,
)


@pytest.fixture(autouse=True)
def isolated_diagnostics(tmp_path, monkeypatch):
    yield from isolate_trace_directory(tmp_path, monkeypatch)


def manager():
    service.set_enabled(True, state_failure_traces=True)
    return SimpleNamespace(
        game_id=str(uuid4()), turn_id=str(uuid4()), state=SimpleNamespace(inventory=["confirmed"])
    )


@step("synthetic.failed_check")
async def failed_check(owner, payload, *, retries=0):
    service.detail("detail.llm.request", request={"messages": [{"content": payload}]})
    reject("items", payload[:6], "An independently checked proposal was rejected.")
    for _ in range(retries):
        service.detail("detail.llm.response", response=payload + " corrected")
        reject("items", "retry", "The corrected proposal was still invalid.")
    service.detail("detail.llm.response", response=payload)
    return {"accepted": False}


@pytest.mark.parametrize("retries", [0, 1])
async def test_separate_checks_keep_complete_requests_retries_and_final_state(retries):
    host = manager()
    first = "FIRST " + "Neutral complete source Ω\n" * 1500
    second = "SECOND neutral request"

    @step("synthetic.successful_check")
    async def successful_check(owner):
        service.detail("detail.engine.snapshot", state="UNRELATED_SUCCESS" * 1000)
        return True

    with turn_context(host, ("Neutral action",), {}):
        assert await failed_check(host, first, retries=retries) == {"accepted": False}
        assert await successful_check(host) is True
        assert await failed_check(host, second) == {"accepted": False}

    assert len(trace_files()) == 2
    packets = [trace_rows(path) for path in trace_files()]
    parents = set()
    for rows in packets:
        request = event_payloads(rows, "detail.llm.request")[0]
        own = request["request"]["messages"][0]["content"]
        responses = event_payloads(rows, "detail.llm.response")
        assert responses[-1]["response"] == own
        assert len(responses) == 1 + (retries if own == first else 0)
        rejected = event_payloads(rows, "state.rejected")
        assert len(rejected) == rows[-1]["rejected_count"] == len(responses)
        assert len(rows[-1]["rejection_summaries"]) == len(rejected)
        assert own in (first, second)
        assert {item["reason_code"] for item in rejected} <= {own[:6], "retry"}
        text = str(rows)
        assert ("SECOND neutral request" if own == first else "FIRST ") not in text
        assert "UNRELATED_SUCCESS" not in text
        assert (
            event_payloads(rows, "detail.engine.turn.started")[0]["player_input"]
            == "Neutral action"
        )
        final = event_payloads(rows, "detail.engine.turn.ended")[0]
        assert final["state"]["inventory"] == ["confirmed"]
        assert rows[0]["trace_id"] == rows[-1]["trace_id"]
        parents.add(rows[0]["parent_trace_id"])
    assert len(parents) == 1
    assert len({rows[0]["trace_id"] for rows in packets}) == 2


async def test_parent_and_child_failures_remain_one_check_next_to_an_independent_failure():
    host = manager()

    @step("synthetic.parent")
    async def parent(owner):
        await failed_check(owner, "CHILD source")
        reject("state", "parent", "The same parent check remains unconfirmed.")

    with turn_context(host, ("Neutral action",), {}):
        await parent(host)
        await failed_check(host, "OTHER source")
    assert len(trace_files()) == 2
    grouped = next(trace_rows(path) for path in trace_files() if "CHILD source" in path.read_text())
    assert grouped[-1]["rejected_count"] == 2
    assert {row["reason_code"] for row in event_payloads(grouped, "state.rejected")} == {
        "CHILD ",
        "parent",
    }
    assert "OTHER source" not in str(grouped)


async def test_missing_step_metadata_retains_the_full_packet_with_explicit_fallback():
    host = manager()
    with turn_context(host, ("Neutral action",), {}):
        await failed_check(host, "CHECK source")
        reject("state", "unscoped", "A failure outside a traced check.")
    assert len(trace_files()) == 1
    rows = trace_rows()
    assert rows[-1]["rejected_count"] == 2
    assert rows[-1]["packet_isolation"]["status"] == "unavailable"
    assert rows[-1]["packet_isolation"]["reason"] == "unscoped_failure"
    assert len(event_payloads(rows, "state.rejected")) == 2


async def test_repeated_operation_ids_never_modify_an_existing_packet():
    host = manager()
    with turn_context(host, ("First neutral attempt",), {}):
        await failed_check(host, "FIRST source")
    original = trace_files()[0]
    before = original.read_bytes()
    with turn_context(host, ("Second neutral attempt",), {}):
        await failed_check(host, "OTHER source")
    assert len(trace_files()) == 2
    assert original.read_bytes() == before


@pytest.mark.parametrize(
    "reason", ["capture_overflow", "incomplete_rejections", "ambiguous_step_graph"]
)
def test_uncertain_boundaries_preserve_every_original_row(reason):
    from copy import deepcopy

    from backend.core.state_rejection_packets import split

    rows = [
        {"event": "state.trace.started", "trace_id": "original"},
        {
            "event": "state.rejected",
            "step_id": "a",
            "parent_step_id": None,
            "detail": {"reason": "kept whole"},
        },
        {
            "event": "state.trace.ended",
            "trace_id": "original",
            "rejected_count": 1,
            "capture_overflow": {"omitted_events": 0},
        },
    ]
    if reason == "capture_overflow":
        rows[-1]["capture_overflow"]["omitted_events"] = 1
    elif reason == "incomplete_rejections":
        rows[-1]["rejected_count"] = 2
    else:
        rows[1]["parent_step_id"] = "a"
    before = deepcopy(rows)
    packets = split(rows)
    assert len(packets) == 1 and packets[0][:-1] == rows[:-1]
    assert packets[0][-1]["packet_isolation"] == {"status": "unavailable", "reason": reason}
    assert rows == before


@pytest.mark.parametrize("limit", ["MAX_STEPS", "MAX_STEP_DEPTH"])
def test_graph_limits_admit_the_boundary_and_preserve_an_oversized_capture(monkeypatch, limit):
    from backend.core import state_rejection_packets as packets

    rows = [
        {"event": "state.trace.started", "trace_id": "original"},
        {"event": "state.rejected", "step_id": "a", "parent_step_id": None},
        {"event": "state.trace.ended", "trace_id": "original", "rejected_count": 1},
    ]
    monkeypatch.setattr(packets, limit, 1)
    assert packets.split(rows)[0][-1]["packet_isolation"]["status"] == "isolated"
    rows.insert(2, {"event": "metadata", "step_id": "b", "parent_step_id": None})
    rows[1]["parent_step_id"] = "b"
    result = packets.split(rows)
    assert len(result) == 1 and result[0][:-1] == rows[:-1]
    assert result[0][-1]["packet_isolation"] == {
        "status": "unavailable",
        "reason": "step_graph_limit",
    }
