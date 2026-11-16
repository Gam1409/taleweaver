"""Real opt-in trace packets retain rejected domain evidence while gameplay stays unchanged."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.npc_presentation import PortraitPreferences
from backend.core.state_rejection_trace import scope
from backend.core.system_diagnostics import service
from backend.engine.chpm import inference, proposal_attempt
from backend.engine.chpm import runtime as chpm_runtime
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.schema import Settings, Usage
from backend.engine.chpm.state import load, save
from backend.engine.narrated_movement.runtime import _event
from backend.engine.npc_presentation import diagnostics, runtime
from backend.models.session_state import SessionState
from tests.state_trace_support import (
    event_payloads,
    isolate_trace_directory,
    trace_files,
    trace_rows,
)
from tests.test_chpm_runtime import prepared
from tests.test_narrated_movement_guards import move, pending
from tests.test_state_rejection_emotion_domains import Candidate, _footer
from tests.test_state_rejection_location_learning import BOUND_SECRET, database_error
from tests.test_vn_turn_integration import seed_vn


@pytest.fixture(autouse=True)
def trace_directory(tmp_path, monkeypatch):
    yield from isolate_trace_directory(tmp_path, monkeypatch)


@pytest.mark.parametrize("enabled,detailed", [(False, False), (True, False), (True, True)])
def test_domain_rejections_do_not_create_packets_without_failure_toggle(enabled, detailed):
    service.set_enabled(enabled, detailed_logging=detailed)
    source = pending([move(basis="intention")])
    before = deepcopy(source.before)
    with scope(session_id="synthetic-session", operation="movement"):
        event, accepted, errors = _event(source)
    assert errors and not accepted and not event.moved_entities
    assert source.before == before
    assert trace_files() == []


@pytest.mark.parametrize("detailed", [False, True])
def test_rejection_packets_include_full_source_and_metadata_independently(detailed):
    service.set_enabled(True, detailed_logging=detailed, state_failure_traces=True)
    full_context = "Synthetic source context. " * 5000
    source = pending([move(destination_scene_id="FAR")])
    source.before["full_context"] = full_context
    before = deepcopy(source.before)
    turn = runtime.PresentationTurn(
        PortraitPreferences(emotion_palette=True, character_thoughts=True), {"npc": "Keeper"}
    )
    entry = {"npc_id": "npc", "emotion": "joy", "intensity": "high", "thought": "I will wait."}
    with scope(session_id="synthetic-session", turn_id="synthetic-turn", operation="state_update"):
        service.detail(
            "detail.llm.request",
            messages=[{"content": full_context}],
            api_key="synthetic-credential",
        )
        event, accepted, errors = _event(source)
        assert turn.clean("Story." + _footer([entry])) == "Story."
    assert errors and not accepted and not event.moved_entities
    assert source.before == before
    assert turn.payload("Story.")["npcs"] == {"npc": {"thought": "I will wait."}}
    assert len(trace_files()) == 1
    rows = trace_rows()
    evidence = event_payloads(rows, "state.rejected")
    movement = next(row for row in evidence if row["domain"] == "movement")
    emotion = next(row for row in evidence if row["domain"] == "emotion")
    assert movement["details"]["source_context"] == before
    assert emotion["details"]["proposal"] == entry
    assert rows[0]["context"]["session_id"] == "synthetic-session"
    assert event_payloads(rows, "detail.llm.request")[0]["messages"][0]["content"] == full_context
    assert "synthetic-credential" not in trace_files()[0].read_text()


def test_confirmed_neutral_unknown_and_empty_changes_do_not_persist_failure_packet():
    service.set_enabled(True, state_failure_traces=True)
    with scope(session_id="synthetic-session"):
        assert _event(pending([]))[1:] == ([], [])
        for entry in (
            [],
            [{"npc_id": "npc", "emotion": "calm", "intensity": 0}],
            [{"npc_id": "npc", "emotion": "unknown", "intensity": 0}],
        ):
            turn = runtime.PresentationTurn(
                PortraitPreferences(emotion_palette=True), {"npc": "Keeper"}
            )
            text = turn.clean("Story." + _footer(entry))
            turn.clean(text)
            diagnostics.report(
                SimpleNamespace(state=SimpleNamespace(session_id="synthetic-session")),
                turn,
                text,
                completed=True,
            )
    assert trace_files() == []


async def test_repaired_psychological_proposal_persists_rejected_attempt_without_rejecting_result(
    monkeypatch,
):
    service.set_enabled(True, state_failure_traces=True)
    request = AsyncMock(side_effect=[Candidate(value="invalid"), Candidate(value="accepted")])
    monkeypatch.setattr(inference, "request", request)

    def accept(candidate):
        if candidate.value == "invalid":
            raise ChpmError("No observation supports this proposed feeling.")
        return candidate

    with scope(session_id="synthetic-session", operation="chpm"):
        result = await proposal_attempt.request(
            SimpleNamespace(),
            Settings(mode="live", actor_ids=["npc"]),
            Usage(),
            "Authored policy",
            {"observed": "The archive is quiet."},
            Candidate,
            {"actor_id": ["npc"]},
            accept,
        )
    assert result.value == "accepted" and request.await_count == 2
    rejected = event_payloads(trace_rows(), "state.rejected")
    assert len(rejected) == 1
    assert rejected[0]["details"]["proposal"] == {"value": "invalid"}


async def test_refused_psychological_save_is_traced_without_persisting_invalid_state(db_session):
    service.set_enabled(True, detailed_logging=False, state_failure_traces=True)
    _, _, state, _ = await seed_vn(db_session)
    original = deepcopy(state.entity_states)
    proposed = load(state)
    proposed.settings.mode = "invalid"
    with scope(session_id=state.session_id, operation="chpm"), pytest.raises(ChpmError):
        save(state, proposed, expected_revision=proposed.revision)
    await db_session.commit()
    identifier = state.id
    db_session.expire_all()
    stored = await db_session.get(SessionState, identifier)
    assert stored.entity_states == original
    service.close()
    rows = trace_rows()
    rejected = event_payloads(rows, "state.rejected")
    assert rejected[0]["reason_code"] == "chpm.save_invalid"
    assert rejected[0]["details"]["proposal"]["settings"]["mode"] == "invalid"


def test_persisted_failure_toggle_remains_independent_after_restart():
    service.set_enabled(True, detailed_logging=False, state_failure_traces=True)
    service.close()
    service.initialize()
    assert service.state_failure_traces is True and service.detailed_logging is False
    with scope(session_id="synthetic-session"):
        _event(pending([move(basis="attempt")]))
    assert event_payloads(trace_rows(), "state.rejected")[0]["domain"] == "movement"


@pytest.mark.parametrize("kind", ["sqlalchemy", "dbapi", "chained"])
def test_chpm_preparation_failure_never_serializes_database_values(kind):
    service.set_enabled(True, state_failure_traces=True)
    host = prepared()
    before = deepcopy(host.state.entity_states)
    error = database_error(kind)
    with scope(session_id="session"), pytest.raises(ChpmError):
        chpm_runtime._preparation_failed(host, host._chpm_turn, error)
    assert host.state.entity_states == before
    record = trace_files()[0].read_text()
    assert BOUND_SECRET not in record and "INSERT INTO private_records" not in record
    failure = event_payloads(trace_rows(), "state.rejected")[0]
    assert failure["details"]["error"]["type"] == type(error).__name__
