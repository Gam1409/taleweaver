"""Skipped item checks explain the real guard and preserve the original possessions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.engine.narrated_items.runtime import KEY, MAX_NARRATION, reconcile_items
from backend.engine.narrated_items.schema import ItemExtraction
from backend.engine.physical_conditions.schema import KEY as PHYSICAL_KEY
from backend.engine.visual_novel.continuity import PLAYER, prepare_intent
from backend.engine.visual_novel.item_rejections import rejection_reason
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.state_response_fixture import extraction
from tests.test_narrated_items import fixtures
from tests.test_vn_continuity import manager as continuity_manager
from tests.test_vn_turn_integration import TurnRoles, final_payload, install_roles, seed_vn


def reconciliation_fixture(monkeypatch):
    actors, snapshot = fixtures()
    manager = SimpleNamespace(
        avatar=SimpleNamespace(**actors[PLAYER]),
        state=SimpleNamespace(entity_states={}, session_id="SESSION", current_scene_id="ROOM"),
        game_id="SESSION",
        user=SimpleNamespace(),
        db=SimpleNamespace(),
        _vn_player_message_id="TURN",
    )
    npc = SimpleNamespace(id="NPC", entity_type="NPC", age_years=30)
    call = AsyncMock(return_value=extraction(ItemExtraction))
    prefix = "backend.engine.narrated_items.runtime."
    monkeypatch.setattr(prefix + "session_objects", AsyncMock(return_value=[npc]))
    monkeypatch.setattr(prefix + "actor_records", lambda *_: actors)
    monkeypatch.setattr(prefix + "possession_snapshot", lambda *_: snapshot)
    monkeypatch.setattr(prefix + "detail_settings", lambda *_: {"detailed": True})
    monkeypatch.setattr(prefix + "release_for_model", AsyncMock())
    monkeypatch.setattr(prefix + "scene_continuity.prepare", AsyncMock(return_value={}))
    monkeypatch.setattr(prefix + "narrated_movement.prepare", AsyncMock(return_value={}))
    monkeypatch.setattr(prefix + "role_timeout", lambda *_: 10)
    monkeypatch.setattr(
        prefix + "GameMasterLLM.for_role",
        lambda *_: SimpleNamespace(model="test", aexecute_complex_task=call),
    )
    return manager, call


@pytest.mark.parametrize("characters,called", [(MAX_NARRATION, True), (MAX_NARRATION + 1, False)])
async def test_narration_limit_is_inclusive_and_reports_actual_counts(
    monkeypatch, characters, called
):
    manager, call = reconciliation_fixture(monkeypatch)
    messages = await reconcile_items(manager, "X" * characters, completed=True, resolution="")
    assert call.await_count == int(called)
    if called:
        assert not messages
        assert manager.state.entity_states[KEY]["status"] == "complete"
        return
    check = manager.state.entity_states[KEY]
    assert check["reason_code"] == "narration_limit"
    assert check["narration_characters"] == characters
    assert check["narration_limit"] == MAX_NARRATION
    assert str(characters) in messages[0] and str(MAX_NARRATION) in messages[0]


async def test_blocked_short_reply_reports_rules_instead_of_a_possible_size_failure(monkeypatch):
    manager, call = reconciliation_fixture(monkeypatch)
    messages = await reconcile_items(
        manager, "A short completed reply.", completed=True, resolution="", blocked=True
    )
    call.assert_not_awaited()
    check = manager.state.entity_states[KEY]
    assert check["reason_code"] == "rules_rejected"
    assert "earlier rules" in check["reason"]
    assert "oversized" not in check["reason"]
    assert "rules" in messages[0]


def test_successful_preparation_clears_the_previous_turns_rejection():
    manager = continuity_manager([{"id": "key", "name": "Key"}])
    manager._vn_player_message_id = "FIRST"
    rejected = prepare_intent(manager, {"removed_inventory_item_ids": ["missing"]}, [])
    assert rejected.removed_inventory_item_ids == []
    assert manager._vn_item_rejection["message_id"] == "FIRST"
    assert "does not carry" in manager._vn_item_rejection["reason"]
    manager._vn_player_message_id = "SECOND"
    assert rejection_reason(manager, []) == ""
    prepare_intent(manager, {}, [])
    assert manager._vn_item_rejection is None


def test_unexpected_internal_error_text_is_not_forwarded_to_the_story(monkeypatch):
    manager = continuity_manager()

    def fail(*_args):
        raise ValueError("SECRET_INTERNAL_PAYLOAD")

    monkeypatch.setattr("backend.engine.visual_novel.continuity._hydrate", fail)
    result = prepare_intent(manager, {}, [])
    assert "SECRET_INTERNAL_PAYLOAD" not in result.narrative_description
    assert "SECRET_INTERNAL_PAYLOAD" not in str(manager._vn_item_rejection)
    assert "canonical possessions" in manager._vn_item_rejection["reason"]


def test_rule_rejection_takes_precedence_and_bounds_only_the_diagnostic_excerpt():
    manager = continuity_manager()
    text = "Rule detail " * 100
    reason = rejection_reason(manager, [text])
    assert reason.startswith("The earlier rules check rejected the action:")
    assert len(reason) < 700
    assert reason.endswith("[diagnostic excerpt]")


async def test_rejected_possession_reason_is_retained_while_independent_state_is_checked(
    monkeypatch,
):
    monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", "Lina continues talking.")

    class InvalidOwnershipRoles(TurnRoles):
        async def structured(self, *args, **kwargs):
            result = await super().structured(*args, **kwargs)
            if type(result).__name__.startswith("VNProgressionIntent"):
                result.removed_inventory_item_ids = ["NOT_CARRIED"]
            return result

    roles = InvalidOwnershipRoles()
    install_roles(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, avatar, _, _ = await seed_vn(db)
        inventory = list(avatar.inventory)
        from backend.engine.gameplay.manager import GameTurnManager

        events = [
            event async for event in GameTurnManager(db, "session-1", user).process_turn("I wait.")
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
        assert avatar.inventory == inventory
        assert "does not carry" in "".join(events)
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "session-1"))
        check = state.entity_states[KEY]
        assert check["reason_code"] == "rules_rejected"
        assert "The player does not carry this item." in check["reason"]
        physical = state.entity_states[PHYSICAL_KEY]["last_check"]
        assert physical["status"] == "complete"
        assert physical["accepted"] == [] and physical["rejected"] == []
        assert physical["proposed_count"] == 0
    calls = [call for name, *call in roles.calls if name == "SharedItemExtraction"]
    assert len(calls) == 1
    import json

    payload = json.loads(calls[0][0][1])
    assert payload["item_changes_allowed"] is False
    assert PLAYER in payload["independent_state_scope"]["blocked_subject_ids"]
    assert len(roles.prompts) == 1
