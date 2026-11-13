"""State rejection hooks observe existing decisions without changing their outcomes."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.engine import debug_engine
from backend.engine.narrated_items import runtime as items
from backend.engine.physical_conditions import runtime as physical
from backend.engine.scene_continuity import runtime as scene
from backend.engine.scene_staging import shared


def manager(states=None):
    return SimpleNamespace(
        game_id="trace-session",
        state=SimpleNamespace(
            session_id="trace-session",
            current_scene_id="ROOM",
            in_game_time=3,
            entity_states=deepcopy(states or {}),
        ),
    )


@pytest.fixture
def calls(monkeypatch):
    found = []

    def observe(*args, **kwargs):
        found.append((args, kwargs))

    for module in (items, physical, scene, shared, debug_engine):
        monkeypatch.setattr(module, "reject", observe, raising=False)
    return found


@pytest.mark.parametrize(
    "status,details",
    [
        ("complete", {"accepted": [{"item": {"id": "BOX"}}], "rejected": ["Bad source"]}),
        ("needs_review", {"unconfirmed_sections": ["condition_updates"]}),
        ("failed", {"failure": {"code": "invalid_schema"}}),
    ],
)
def test_item_audit_keeps_partial_acceptance_and_explains_rejection(calls, status, details):
    host = manager()
    items._status(host, "reply", "The box is open.", status, **details)
    assert calls
    stored = host.state.entity_states[items.KEY]
    assert stored["status"] == status
    assert all(stored[key] == value for key, value in details.items())


def test_confirmed_empty_item_response_is_not_a_rejection(calls):
    items._status(manager(), "reply", "The room is quiet.", "complete", accepted=[], rejected=[])
    assert not calls


def test_invalid_property_quote_is_traced_without_accepting_the_changed_value(calls):
    host = manager()
    proposal = {
        "operation": "record",
        "target_id": "BOX",
        "kind": "item_state",
        "part": "state",
        "detail": "opened",
        "evidence": "The box is open.",
    }
    pending = physical.stage(host, [proposal], {"BOX"})
    pending.item_targets = {"BOX"}
    result = physical.finish(host, SimpleNamespace(id="reply", content="The box is open."))
    assert result and calls
    assert host.state.entity_states[physical.KEY]["last_check"]["rejected"]
    assert not host.state.entity_states[physical.KEY]["conditions"]
    assert "opened" in str(calls)


def test_confirmed_empty_physical_updates_are_not_a_rejection(calls):
    host = manager()
    physical.stage(host, [], set())
    assert physical.finish(host, SimpleNamespace(id="reply", content="Quiet room.")) == []
    assert not calls


def test_physical_stale_write_is_traced_and_current_state_survives(calls):
    host = manager()
    physical.stage(host, [], set())
    host.state.entity_states = {physical.KEY: {"changed": True}}
    before = deepcopy(host.state.entity_states)
    assert physical.finish(host, SimpleNamespace(id="reply", content="Quiet room."))
    assert calls and host.state.entity_states == before


def test_unconfirmed_physical_response_has_its_original_reason(calls):
    host = manager()
    physical.stage(host, [], set(), error="The response did not confirm condition_updates.")
    assert physical.finish(host, SimpleNamespace(id="reply", content="Quiet room.")) == []
    assert calls and "did not confirm" in str(calls)


def test_bad_scene_proposal_is_traced_without_recording_a_fact(calls):
    host = manager()
    host._pending_scene_continuity = scene.Pending(
        None,
        "ROOM",
        "Quiet room.",
        {"ROOM", "BOX"},
        set(),
        updates=[{"unknown": True}],
    )
    assert scene.finish(host, SimpleNamespace(id="reply", content="The box is open."))
    assert calls
    assert not host.state.entity_states[scene.KEY]["records"]


def test_missing_scene_section_is_distinguished_from_a_confirmed_empty_list(calls):
    host = manager()
    host._pending_scene_continuity = scene.Pending(
        None,
        "ROOM",
        "Quiet room.",
        {"ROOM"},
        set(),
        updates=[],
        unconfirmed_sections=("final_frame_actions",),
    )
    scene.finish(host, SimpleNamespace(id="reply", content="Quiet room."))
    assert calls and "final_frame_actions" in str(calls)


def test_scene_empty_and_repeated_noop_are_not_rejections(calls):
    host = manager()
    host._pending_scene_continuity = scene.Pending(
        None,
        "ROOM",
        "Quiet room.",
        {"ROOM"},
        set(),
        updates=[],
        actions=[],
    )
    assert scene.finish(host, SimpleNamespace(id="reply", content="Quiet room.")) == []
    assert scene.finish(host, SimpleNamespace(id="reply", content="Quiet room.")) == []
    assert not calls


def test_staging_invalidation_preserves_the_actual_failure_reason(calls):
    host = manager()
    shared.invalidate(host.state, "Quiet room.", "Source changed during extraction.")
    assert calls and "Source changed" in str(calls)


@pytest.mark.asyncio
async def test_debug_state_error_is_traced_without_changing_the_result(monkeypatch, calls):
    expected = "DEBUG ERROR: The selected state could not be changed."
    handler = AsyncMock(return_value=expected)
    monkeypatch.setitem(debug_engine._HANDLERS, "trace_probe", handler)
    state = manager().state
    result = await debug_engine.DebugEngine.handle_debug_command(None, state, "trace_probe BOX")
    assert result == expected and handler.await_count == 1
    assert calls and "trace_probe BOX" in str(calls)
    assert state.entity_states == {}


@pytest.mark.asyncio
async def test_debug_successful_noop_is_not_a_rejection(monkeypatch, calls):
    handler = AsyncMock(return_value="DEBUG: Already in this location.")
    monkeypatch.setitem(debug_engine._HANDLERS, "trace_probe", handler)
    state = manager().state
    assert await debug_engine.DebugEngine.handle_debug_command(None, state, "trace_probe")
    assert not calls
