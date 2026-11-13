"""Real turn and recovery boundaries retain failures without changing saved outcomes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.core.state_rejection_trace import scope
from backend.core.system_diagnostics import service
from backend.engine import debug_engine
from backend.engine.clothing.recovery_context import KEY as RECOVERY_KEY
from backend.engine.clothing.recovery_schema import RecoveryProposal
from backend.engine.physical_conditions import runtime as physical
from backend.engine.scene_staging.shared import apply_extraction
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldScene
from tests.state_trace_support import (
    event_payloads,
    isolate_trace_directory,
    trace_files,
    trace_rows,
)
from tests.test_game_loop import _seed_game_context
from tests.test_vn_turn_integration import seed_vn


@pytest.fixture(autouse=True)
def isolated_diagnostics(tmp_path, monkeypatch):
    yield from isolate_trace_directory(tmp_path, monkeypatch)


@pytest.mark.parametrize("enabled", [False, True])
async def test_debug_rejection_packet_spans_the_actual_turn_and_saved_state(
    db_session, monkeypatch, enabled
):
    user, _, _, state = await _seed_game_context(db_session)
    state.is_debug_enabled = True
    db_session.add(
        WorldScene(id="START", session_id=state.session_id, label="Room", description="Quiet room.")
    )
    await db_session.commit()
    service.set_enabled(True, detailed_logging=False, state_failure_traces=enabled)

    async def handler(_db, current, *_args):
        service.detail("detail.llm.response", response={"candidate": "unavailable BOX"})
        current.entity_states = {"BOX": {"inspected": True}}
        assert not trace_files()  # A child command must not flush before its caller saves.
        return "DEBUG ERROR: The proposed box placement is unavailable."

    monkeypatch.setitem(debug_engine._HANDLERS, "trace_probe", handler)
    host = GameTurnManager(db_session, state.session_id, user)
    chunks = [chunk async for chunk in host.process_turn("/debug trace_probe BOX")]
    assert any(chunk.startswith("event: final") for chunk in chunks)
    identifier = state.id
    db_session.expire_all()
    stored = await db_session.get(SessionState, identifier)
    assert stored.entity_states["BOX"] == {"inspected": True}
    assert len(trace_files()) == int(enabled)
    if not enabled:
        return
    rows = trace_rows()
    assert rows[0]["context"]["operation"] == "turn"
    assert rows[0]["context"]["turn_id"]
    assert event_payloads(rows, "detail.engine.turn.started")
    assert event_payloads(rows, "detail.engine.turn.ended")
    assert event_payloads(rows, "detail.llm.response")[0]["response"]["candidate"]
    assert event_payloads(rows, "state.rejected")[0]["reason_code"] == "command_rejected"


async def test_successful_debug_noop_creates_no_failure_file(db_session, monkeypatch):
    user, _, _, state = await _seed_game_context(db_session)
    state.is_debug_enabled = True
    service.set_enabled(True, state_failure_traces=True)
    handler = AsyncMock(return_value="DEBUG: The box is already here.")
    monkeypatch.setitem(debug_engine._HANDLERS, "trace_probe", handler)
    assert (
        await debug_engine.DebugEngine.handle_debug_command(
            db_session, state, "trace_probe", user=user
        )
        == "DEBUG: The box is already here."
    )
    assert not trace_files()


@pytest.mark.parametrize("focused", [False, True])
async def test_empty_recovery_distinguishes_no_change_from_unconfirmed_focus(
    db_session, monkeypatch, focused
):
    user, avatar, state, _ = await seed_vn(db_session)
    state.is_debug_enabled = True
    service.set_enabled(True, state_failure_traces=True)
    router = SimpleNamespace(
        model="local-test", aexecute_complex_task=AsyncMock(return_value=RecoveryProposal())
    )
    monkeypatch.setattr(
        "backend.engine.clothing.recovery.GameMasterLLM.for_role", lambda *_: router
    )
    args = 'wardrobe_preview LINA small "missing box"' if focused else "wardrobe_preview LINA"
    result = await debug_engine.DebugEngine.handle_debug_command(
        db_session, state, args, user=user, avatar=avatar
    )
    assert "preview ready" in result
    router.aexecute_complex_task.assert_awaited_once()
    assert not state.entity_states[RECOVERY_KEY]["accepted"]
    assert len(trace_files()) == int(focused)
    if focused:
        rejection = event_payloads(trace_rows(), "state.rejected")[0]
        assert rejection["reason_code"] == "focused_recovery_unconfirmed"
        assert rejection["details"]["focus"] == "missing box"


def test_partial_item_state_rejection_retains_accepted_fact_and_complete_cause():
    service.set_enabled(True, detailed_logging=False, state_failure_traces=True)
    host = SimpleNamespace(
        state=SimpleNamespace(session_id="synthetic", in_game_time=1, entity_states={})
    )
    base = {"operation": "record", "target_id": "BOX", "kind": "item_state"}
    proposals = [
        {**base, "part": "closure", "detail": "open", "evidence": "The box is open."},
        {**base, "part": "fill", "detail": "filled", "evidence": "The box is empty."},
    ]
    with scope(session_id="synthetic", operation="condition_check"):
        pending = physical.stage(host, proposals, {"BOX"})
        pending.item_targets = {"BOX"}
        result = physical.finish(
            host, SimpleNamespace(id="reply", content="The box is open. The box is empty.")
        )
    ledger = host.state.entity_states[physical.KEY]
    assert result and len(ledger["conditions"]) == 1
    assert next(iter(ledger["conditions"].values()))["detail"] == "open"
    rejection = event_payloads(trace_rows(), "state.rejected")[0]
    assert rejection["details"]["proposals"] == proposals
    assert rejection["details"]["errors"] == ledger["last_check"]["rejected"]
    assert event_payloads(trace_rows(), "detail.engine.completed")


def test_invalid_staging_candidate_is_retained_before_filtering():
    service.set_enabled(True, state_failure_traces=True)
    host = SimpleNamespace(
        avatar=SimpleNamespace(id="PLAYER", inventory=[], equipment={}),
        state=SimpleNamespace(
            session_id="synthetic", current_scene_id="ROOM", entity_states={}, inventory=[]
        ),
    )
    proposals = {
        "changes": [
            {"entity_id": "PLAYER", "posture": "INVALID_POSE", "evidence": "The player pauses."}
        ],
        "props": [],
        "explicit": [],
    }
    with scope(session_id="synthetic", operation="scene_check"):
        apply_extraction(
            host, "The player pauses.", [{"id": "PLAYER", "name": "Hero"}], [], proposals
        )
    rejection = event_payloads(trace_rows(), "state.rejected")[0]
    assert rejection["details"]["proposals"] == proposals
    assert not rejection["details"]["resolved"]["changes"]
