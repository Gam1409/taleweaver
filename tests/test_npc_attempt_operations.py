"""Attempt fences and operation identity survive retries, ordering and publication."""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from backend.engine import turn_controls
from backend.engine.chpm import tool_operations
from backend.engine.chpm.errors import RecoverableChpmError
from backend.engine.clothing.visuals import session_objects
from backend.engine.npc_actions import control, publication
from backend.engine.npc_actions.contracts import Give, Take
from backend.engine.npc_actions.publication import publish
from backend.engine.turn_replay import stream
from backend.engine.visual_novel.continuity import possession_snapshot
from backend.engine.visual_novel.item_rejections import current_rejection, remember
from tests.conftest import TestSessionLocal
from tests.npc_control_support import bind_turn
from tests.test_chpm_native_notebook_loop import call
from tests.test_npc_action_previews import fixture as preview_fixture
from tests.test_npc_action_publication import fixture


def host():
    result = SimpleNamespace(
        game_id="session",
        turn_id="transport",
        _vn_player_message_id="input",
        state=SimpleNamespace(current_scene_id="ROOM", entity_states={}),
    )
    turn_controls.begin(result)
    turn_controls.bind_input(
        result, SimpleNamespace(id="input", revision_id="revision", content="I wait.")
    )
    return result


def test_attempt_reentry_preserves_parent_but_never_reuses_an_input_attempt():
    manager = host()
    original = turn_controls.scope(manager, "proposal")
    assert turn_controls.bind_current(manager, original, "proposal")
    first = manager._turn_control_attempt
    turn_controls.begin(manager)
    assert manager.turn_id == first.parent_turn_id == "transport"
    assert manager._turn_control_attempt.id != original["attempt_id"]
    assert not turn_controls.bind_current(manager, original, "proposal")


@pytest.mark.parametrize("change", ["attempt", "input", "revision", "hash", "phase", "malformed"])
def test_structural_binding_rejects_foreign_stale_or_malformed_records(change):
    manager = host()
    record = turn_controls.scope(manager, "proposal")
    fields = {
        "attempt": "attempt_id",
        "input": "input_id",
        "revision": "input_revision",
        "hash": "input_hash",
        "phase": "phase",
    }
    if change == "malformed":
        record["attempt_id"] = {"invalid": True}
    else:
        record[fields[change]] = "foreign"
    assert not turn_controls.bind_current(manager, record, "proposal")


def test_snapshot_fingerprints_do_not_reject_independent_owner_changes():
    manager = host()
    record = turn_controls.scope(manager, "proposal")
    manager.state.entity_states = {"npc": {"inventory": [{"id": "KEY"}]}}
    assert turn_controls.scope(manager, "proposal")["state_revision"] != record["state_revision"]
    assert turn_controls.bind_current(manager, record, "proposal")


async def test_stream_completion_and_cancellation_close_the_original_attempt(monkeypatch):
    manager = host()
    captures = []

    async def run(*_args):
        captures.append(turn_controls.scope(manager, "proposal"))
        yield "event: chunk\ndata: {}\n\n"

    monkeypatch.setattr(stream, "_run", run)
    first = stream.run(manager, "I wait.", False, None, None, None)
    await anext(first)
    await first.aclose()
    assert not turn_controls.bind_current(manager, captures[0])
    second = stream.run(manager, "I wait.", False, None, None, None)
    assert len([chunk async for chunk in second]) == 1
    assert captures[0]["attempt_id"] != captures[1]["attempt_id"]
    assert not turn_controls.bind_current(manager, captures[1])


def test_preliminary_failure_is_bound_to_phase_and_not_classified_from_prose():
    manager = host()
    captured = turn_controls.scope(manager, "preliminary_items")
    first_message = remember(manager, ValueError("Unknown or unavailable item."), captured=captured)
    first = deepcopy(current_rejection(manager))
    assert (
        first["phase"] == "preliminary_items"
        and first["reason_code"] == "preliminary_item_rejected"
    )
    assert first_message == remember(
        manager, ValueError("Unrelated private diagnostic text."), captured=captured
    )
    assert first["operation_id"] != current_rejection(manager)["operation_id"]
    assert "Unknown or unavailable item." not in first_message
    manager._turn_control_input["input_revision"] = "edited"
    assert current_rejection(manager) is None


def batch_tools(manager):
    _, _, draft = preview_fixture()
    draft.scope = replace(draft.scope, control=turn_controls.scope(manager, "npc_command_preview"))
    tools = SimpleNamespace(
        observation=SimpleNamespace(
            message_id="input",
            revision_id="revision",
            content_hash=manager._turn_control_input["input_hash"],
        ),
        mind=SimpleNamespace(genesis=SimpleNamespace(scope=SimpleNamespace(observer_id="npc"))),
        actions=draft,
        current_actions=lambda: draft,
    )
    return tools


def test_same_batch_take_give_feedback_uses_operation_identity_after_results_reorder():
    manager = host()
    tools = batch_tools(manager)
    requests = [
        Take(tool="take_item", item_id="KEY"),
        Give(tool="give_item", item_id="KEY", recipient_id="other"),
    ]
    calls = (
        call("first", "take_item", {"item_id": "KEY"}),
        call("second", "give_item", {"item_id": "KEY", "recipient_id": "other"}),
    )
    batch = tool_operations.execute(
        manager, tools, calls, requests, captured=tool_operations.capture(manager, tools)
    )
    assert [row["status"] for row in batch.results] == ["staged", "staged"]
    batch.results.reverse()
    pairs = tool_operations.feedback(batch)
    assert [(item.id, result["effect"]["destination_owner"]) for item, result in pairs] == [
        ("first", "npc"),
        ("second", "other"),
    ]
    assert len({row["operation_id"] for row in batch.results}) == 2


@pytest.mark.parametrize(
    "change", ["duplicate", "foreign_attempt", "wrong_operation", "wrong_tool", "missing"]
)
def test_feedback_rejects_structurally_invalid_results(change):
    manager = host()
    tools = batch_tools(manager)
    batch = tool_operations.execute(
        manager,
        tools,
        (call("take", "take_item", {"item_id": "KEY"}),),
        [Take(tool="take_item", item_id="KEY")],
        captured=tool_operations.capture(manager, tools),
    )
    if change == "duplicate":
        batch.results.append(deepcopy(batch.results[0]))
    elif change == "missing":
        batch.results.clear()
    else:
        field = {
            "foreign_attempt": "attempt_id",
            "wrong_operation": "operation_id",
            "wrong_tool": "tool",
        }[change]
        batch.results[0][field] = "foreign"
    with pytest.raises(RecoverableChpmError):
        tool_operations.feedback(batch)


def test_late_response_cannot_obtain_a_new_attempt_or_execute_again():
    manager = host()
    tools = batch_tools(manager)
    captured = tool_operations.capture(manager, tools)
    turn_controls.begin(manager)
    with pytest.raises(RecoverableChpmError, match="inactive attempt"):
        tool_operations.execute(
            manager,
            tools,
            (call("take", "take_item", {"item_id": "KEY"}),),
            [Take(tool="take_item", item_id="KEY")],
            captured=captured,
        )
    assert not tools.actions.requests


async def test_publication_keeps_operation_and_command_ids_across_phases():
    async with TestSessionLocal() as db:
        manager, _, drafts = await fixture(db)
        draft = drafts["LINA"]
        staged = draft.execute(Take(tool="take_item", item_id="KEY"))
        draft.approved = True
        applied = (await publish(manager, draft))[0]
        assert applied["status"] == "applied"
        assert {key: applied[key] for key in ("attempt_id", "operation_id", "command_id")} == {
            key: staged[key] for key in ("attempt_id", "operation_id", "command_id")
        }
        assert (
            staged["phase"] == "npc_command_preview"
            and applied["phase"] == "npc_command_publication"
        )
        assert applied["state_revision_before"] != applied["state_revision_after"]
        assert await publish(manager, draft) == [applied]
        turn_controls.begin(manager)
        assert (await publish(manager, draft))[0]["status"] == "stale"


@pytest.mark.parametrize("change", ["media", "other_npc"])
async def test_cosmetic_or_independent_state_changes_do_not_invalidate_a_current_plan(change):
    async with TestSessionLocal() as db:
        manager, _, drafts = await fixture(db)
        draft = drafts["LINA"]
        draft.execute(Take(tool="take_item", item_id="KEY"))
        key = "__illustration__" if change == "media" else "SECOND"
        manager.state.entity_states = {
            **manager.state.entity_states,
            key: {"caption": "A new view."},
        }
        draft.approved = True
        assert (await publish(manager, draft))[0]["status"] == "applied"


async def test_rollback_retry_uses_a_new_attempt_without_reexecuting_a_cached_old_plan():
    async with TestSessionLocal() as db:
        manager, _, drafts = await fixture(db)
        draft = drafts["LINA"]
        draft.execute(Take(tool="take_item", item_id="KEY"))
        draft.approved = True
        applied = (await publish(manager, draft))[0]
        await db.flush()
        await db.rollback()
        await db.refresh(manager.state)
        await db.refresh(manager.avatar)
        turn_controls.begin(manager)
        stale = (await publish(manager, draft))[0]
        assert stale["status"] == "stale" and stale["operation_id"] == applied["operation_id"]
        assert stale["attempt_id"] == applied["attempt_id"]
        snapshot = possession_snapshot(manager, await session_objects(db, manager.game_id))
        assert snapshot.owners["KEY"] == "__scene__"


async def test_publication_refresh_cannot_rebind_a_late_plan_to_a_new_attempt(monkeypatch):
    async with TestSessionLocal() as db:
        manager, _, drafts = await fixture(db)
        draft = drafts["LINA"]
        staged = draft.execute(Take(tool="take_item", item_id="KEY"))
        draft.approved = True
        rows = await session_objects(db, manager.game_id)

        async def refreshed(*_args):
            turn_controls.begin(manager)
            return rows

        monkeypatch.setattr(publication, "session_objects", refreshed)
        result = (await publish(manager, draft))[0]
        assert result["status"] == "blocked" and result["reason_code"] == "stale"
        assert result["attempt_id"] == staged["attempt_id"] != manager._turn_control_attempt.id
        assert result["operation_id"] == staged["operation_id"]
        assert possession_snapshot(manager, rows).owners["KEY"] == "__scene__"


@pytest.mark.parametrize("change", ["unissued", "duplicate", "missing", "foreign_attempt"])
def test_review_admits_only_complete_host_issued_current_attempt_outcomes(change):
    manager = host()
    turn = SimpleNamespace(
        decisions={},
        action_outcomes={
            "npc": [{"tool": "take_item", "status": "applied", "effect": {"item_id": "KEY"}}]
        },
    )
    bind_turn(manager, turn)
    assert control.validated_outcomes(turn) == turn.action_outcomes
    if change == "duplicate":
        turn.action_outcomes["npc"].append(deepcopy(turn.action_outcomes["npc"][0]))
    elif change == "missing":
        turn.action_outcomes["npc"].clear()
    else:
        field = "operation_id" if change == "unissued" else "attempt_id"
        turn.action_outcomes["npc"][0][field] = "foreign"
    with pytest.raises(control.CommandRejectedError):
        control.validated_outcomes(turn)
