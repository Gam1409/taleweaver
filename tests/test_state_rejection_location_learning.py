"""Silent location and character-learning refusals use the existing opt-in trace capture."""

import sqlite3
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import StatementError

from backend.core.diagnostic_operations import diagnostic_job
from backend.core.state_rejection_trace import scope
from backend.core.system_diagnostics import service
from backend.engine.dynamic_locations import companions
from backend.engine.dynamic_locations import service as locations
from backend.engine.dynamic_locations.schema import (
    CompanionArrival,
    PlaceDecision,
    registry,
)
from backend.engine.npc_journal import worker
from backend.engine.npc_journal.schema import JournalExtraction
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.state_trace_support import (
    event_payloads,
    isolate_trace_directory,
    trace_files,
    trace_rows,
)
from tests.test_npc_journal import journal_world, portrait_world, save_message

__all__ = ["journal_world", "portrait_world"]
ACTION = "I enter the archive."
PROPOSAL = {"label": "Archive", "action_quote": ACTION}
BOUND_SECRET = "synthetic-bound-parameter-must-not-enter-trace"


@pytest.fixture(autouse=True)
def trace_directory(tmp_path, monkeypatch):
    yield from isolate_trace_directory(tmp_path, monkeypatch)


@asynccontextmanager
async def transaction():
    yield


def location_host():
    state = SimpleNamespace(
        current_scene_id="ROOM",
        entity_states={"__dynamic_locations__": {"policy": {"enabled": True}}},
    )
    return SimpleNamespace(
        state=state,
        user=SimpleNamespace(),
        game_id="synthetic-session",
        db=SimpleNamespace(begin_nested=transaction),
        _vn_player_message_id="player-message",
    )


def place_decision():
    return PlaceDecision(
        arrival_now=True,
        player_moves=True,
        local_to_current_scene=True,
        access_allowed=True,
        contradicts_world=False,
        world_scale="building",
        granularity="room",
        purpose="ordinary",
        action_quote=ACTION,
        label="Archive",
        description="A quiet archive.",
        identity_resolution="new",
    )


def prepare_location(monkeypatch, *, outcome=None, error=None):
    context = {
        "existing_place_catalog": {"complete": True},
        "present_npcs": [],
        "source": "Authored context",
    }
    prepare = AsyncMock(return_value=([], [], context, "Recent narration."))
    request = AsyncMock(return_value=outcome, side_effect=error)
    monkeypatch.setattr(locations, "_context", prepare)
    monkeypatch.setattr(
        locations.GameMasterLLM,
        "for_role",
        lambda *_: SimpleNamespace(model="synthetic-model", aexecute_complex_task=request),
    )
    return prepare, request, context


@pytest.mark.parametrize("failure", ["proposal", "quote", "timeout", "decision", "exception"])
async def test_location_rejection_records_original_proposal_and_preserves_intent(
    monkeypatch, failure
):
    service.set_enabled(True, detailed_logging=False, state_failure_traces=True)
    host = location_host()
    raw = deepcopy(PROPOSAL)
    if failure == "proposal":
        raw.pop("action_quote")
    if failure == "quote":
        raw["action_quote"] = "I enter a different place."
    error = TimeoutError("Confirmation timed out") if failure == "timeout" else None
    if failure == "exception":
        error = RuntimeError("Synthetic confirmation failure")
    prepare, request, context = prepare_location(
        monkeypatch, outcome={"arrival_now": True}, error=error
    )
    intent = SimpleNamespace(new_local_place=raw, new_scene_id=None, moved_entities=[])
    before = deepcopy(host.state.entity_states)
    with scope(session_id=host.game_id, operation="dynamic_location"):
        assert (
            await locations.resolve_proposal(
                host, intent, ACTION, [{"content": "Prior source"}], "English"
            )
            is None
        )
    assert intent.new_scene_id is None and intent.moved_entities == []
    assert host.state.entity_states == before
    assert prepare.await_count == request.await_count == int(failure not in {"proposal", "quote"})
    rejected = event_payloads(trace_rows(), "state.rejected")
    assert len(rejected) == 1 and rejected[0]["domain"] == "movement"
    assert rejected[0]["details"]["proposal"] == raw
    assert rejected[0]["details"]["player_message"] == ACTION
    if failure in {"timeout", "decision", "exception"}:
        assert rejected[0]["details"]["context"] == context


@pytest.mark.parametrize("mode", ["disabled", "absent", "already_resolved"])
async def test_location_normal_noops_do_not_record_rejections(monkeypatch, mode):
    service.set_enabled(True, state_failure_traces=True)
    host = location_host()
    if mode == "disabled":
        host.state.entity_states = {}
    prepare, request, _ = prepare_location(monkeypatch)
    intent = SimpleNamespace(
        new_local_place=None if mode == "absent" else PROPOSAL,
        new_scene_id="EXISTING" if mode == "already_resolved" else None,
    )
    with scope(session_id=host.game_id):
        await locations.resolve_proposal(host, intent, ACTION, [], "English")
    prepare.assert_not_awaited()
    request.assert_not_awaited()
    assert trace_files() == []


async def test_confirmed_location_keeps_normal_materialization_without_failure_packet(monkeypatch):
    service.set_enabled(True, state_failure_traces=True)
    host = location_host()
    _, request, _ = prepare_location(monkeypatch, outcome=place_decision())
    materialize = AsyncMock(return_value="ARCHIVE")
    monkeypatch.setattr(locations, "materialize", materialize)
    intent = SimpleNamespace(new_local_place=PROPOSAL, new_scene_id=None, moved_entities=[])
    with scope(session_id=host.game_id):
        await locations.resolve_proposal(host, intent, ACTION, [], "English")
    assert intent.new_scene_id == "ARCHIVE" and request.await_count == 1
    materialize.assert_awaited_once()
    assert trace_files() == []


def test_rejected_companion_checks_are_traced_without_changing_arrival_results():
    service.set_enabled(True, state_failure_traces=True)
    host = location_host()
    context = {
        "present_npcs": [{"npc_id": "GUIDE", "name": "Keeper", "goal": "Private authored goal"}]
    }
    values = [
        CompanionArrival(npc_id="GUIDE", evidence=ACTION),
        CompanionArrival(npc_id="MISSING", evidence=ACTION),
        CompanionArrival(npc_id="GUIDE", evidence="Words the player never said."),
    ]
    with scope(session_id=host.game_id):
        companions.record_arrival(
            host, SimpleNamespace(companions=values), "ARCHIVE", context, ACTION
        )
    arrival = registry(host.state)["last_arrival"]
    assert [row["status"] for row in arrival["companions"]] == ["pending", "rejected", "rejected"]
    rejected = event_payloads(trace_rows(), "state.rejected")
    assert len(rejected) == 2
    assert [row["details"]["proposal"] for row in rejected] == [
        row.model_dump() for row in values[1:]
    ]
    assert all(row["details"]["context"] == context for row in rejected)


@pytest.mark.parametrize("detailed", [False, True])
async def test_disabled_failure_toggle_keeps_location_and_companion_packets_absent(
    monkeypatch, detailed
):
    service.set_enabled(True, detailed_logging=detailed, state_failure_traces=False)
    host = location_host()
    prepare_location(monkeypatch)
    intent = SimpleNamespace(new_local_place={"label": "Invalid"}, new_scene_id=None)
    with scope(session_id=host.game_id):
        await locations.resolve_proposal(host, intent, ACTION, [], "English")
        companions.record_arrival(
            host,
            SimpleNamespace(companions=[CompanionArrival(npc_id="MISSING", evidence=ACTION)]),
            "ARCHIVE",
            {"present_npcs": []},
            ACTION,
        )
    assert intent.new_scene_id is None and trace_files() == []


@pytest.mark.parametrize("stage", ["context", "extract", "save"])
async def test_swallowed_journal_failure_retains_trace_and_existing_failed_task(
    journal_world, monkeypatch, stage
):
    service.set_enabled(True, detailed_logging=False, state_failure_traces=True)
    owner, portraits = journal_world
    narration = "The keeper introduced herself beside the archive door."
    message_id = await save_message(narration)
    if stage == "context":
        monkeypatch.setattr(
            worker,
            "extraction_context",
            AsyncMock(side_effect=ValueError("Synthetic context failure")),
        )
    monkeypatch.setattr(
        worker,
        "extract",
        AsyncMock(
            return_value=JournalExtraction(),
            side_effect=ValueError("Synthetic extraction failure") if stage == "extract" else None,
        ),
    )
    if stage == "save":
        monkeypatch.setattr(
            worker, "_save", AsyncMock(side_effect=ValueError("Synthetic save failure"))
        )

    @diagnostic_job("npc_learning")
    async def run(session_id, user_id):
        return await worker.process_message(message_id, user_id)

    assert await run("portrait-session", owner) is False
    async with TestSessionLocal() as db:
        message = await db.get(ChatMessage, message_id)
        assert message.content == narration and message.npc_journal["status"] == "failed"
    portraits.assert_not_called()
    rows = trace_rows()
    assert rows[0]["context"]["operation"] == "npc_learning"
    rejected = event_payloads(rows, "state.rejected")
    assert len(rejected) == 1 and rejected[0]["reason_code"] == "npc_journal.extraction_failed"
    assert (
        rejected[0]["reason"]
        == {
            "context": "Synthetic context failure",
            "extract": "Synthetic extraction failure",
            "save": "Synthetic save failure",
        }[stage]
    )
    assert rejected[0]["details"]["narration"] == narration
    assert rejected[0]["details"]["message_id"] == message_id


@pytest.mark.parametrize("deferred", [False, True])
async def test_empty_or_deferred_journal_work_is_not_a_rejected_update(
    journal_world, monkeypatch, deferred
):
    service.set_enabled(True, state_failure_traces=True)
    owner, _ = journal_world
    message_id = await save_message("A quiet moment passes in the archive.")
    extract = AsyncMock(return_value=JournalExtraction())
    monkeypatch.setattr(worker, "extract", extract)
    if deferred:
        monkeypatch.setattr(worker.scheduler, "can_start_background", lambda: False)
    with scope(session_id="portrait-session", operation="npc_learning"):
        assert await worker.process_message(message_id, owner) is not deferred
    if not deferred:
        assert await worker.process_message(message_id, owner) is False
    else:
        extract.assert_not_awaited()
    assert trace_files() == []


def database_error(kind):
    original = sqlite3.DatabaseError(BOUND_SECRET)
    if kind == "dbapi":
        return original
    if kind == "chained":
        wrapper = ValueError(BOUND_SECRET)
        wrapper.__cause__ = original
        return wrapper
    return StatementError(
        "Synthetic persistence failure",
        "INSERT INTO private_records VALUES (:note)",
        {"note": BOUND_SECRET},
        original,
    )


@pytest.mark.parametrize("kind", ["sqlalchemy", "dbapi", "chained"])
async def test_location_generic_database_error_never_serializes_bound_values(monkeypatch, kind):
    service.set_enabled(True, state_failure_traces=True)
    host = location_host()
    error = database_error(kind)
    prepare_location(monkeypatch, error=error)
    intent = SimpleNamespace(new_local_place=PROPOSAL, new_scene_id=None)
    before = deepcopy(host.state.entity_states)
    with scope(session_id=host.game_id):
        await locations.resolve_proposal(host, intent, ACTION, [], "English")
    assert intent.new_scene_id is None and host.state.entity_states == before
    record = trace_files()[0].read_text()
    assert BOUND_SECRET not in record and "INSERT INTO private_records" not in record
    failure = event_payloads(trace_rows(), "state.rejected")[0]
    assert failure["details"]["error"]["type"] == type(error).__name__


@pytest.mark.parametrize("kind", ["sqlalchemy", "dbapi", "chained"])
async def test_journal_database_failure_keeps_bound_values_out_of_trace(
    journal_world, monkeypatch, kind
):
    service.set_enabled(True, state_failure_traces=True)
    owner, _ = journal_world
    narration = "The keeper waits beside the archive door."
    message_id = await save_message(narration)
    error = database_error(kind)
    monkeypatch.setattr(worker, "extraction_context", AsyncMock(side_effect=error))
    with scope(session_id="portrait-session", operation="npc_learning"):
        assert await worker.process_message(message_id, owner) is False
    async with TestSessionLocal() as db:
        message = await db.get(ChatMessage, message_id)
        assert message.content == narration and message.npc_journal["status"] == "failed"
    record = trace_files()[0].read_text()
    assert BOUND_SECRET not in record and "INSERT INTO private_records" not in record
    failure = event_payloads(trace_rows(), "state.rejected")[0]
    assert failure["details"]["error"]["type"] == type(error).__name__
