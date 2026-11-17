"""Preliminary possession rejection has scoped prose and a source-bound host gate."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.engine.chpm.state import KEY, load
from backend.engine.gameplay import manager as gameplay
from backend.engine.npc_actions.control import MESSAGES
from backend.engine.visual_novel.continuity import prepare_intent
from backend.engine.visual_novel.item_rejections import (
    current_rejection,
    rejected_targets,
    rejection_reason,
)
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_chpm_action_turn import ActionRoles
from tests.test_chpm_host_turn import run
from tests.test_chpm_notebook_turn import install
from tests.test_chpm_observable_turn import prepare as prepare_controlled
from tests.test_npc_command_resolution_turn import EarlierFailureRoles
from tests.test_vn_continuity import manager as continuity_manager
from tests.test_vn_turn_integration import TurnRoles, final_payload, install_roles, seed_vn

LEGACY_DENIAL = "The attempted item change did not occur; possessions remain unchanged."


def test_rejected_npc_inventory_describes_only_the_preliminary_proposal():
    manager = continuity_manager()
    npc = SimpleNamespace(
        id="NPC",
        entity_type="NPC",
        name="Rin",
        current_scene_id=manager.state.current_scene_id,
        is_hidden=False,
        inventory=[],
        metadata_json={},
    )
    result = prepare_intent(
        manager,
        {"updated_entities": [{"entity_id": "NPC", "inventory": [{"name": "Unknown item"}]}]},
        [npc],
    )
    assert "The preliminary item proposal was not applied." in result.narrative_description
    assert MESSAGES["preliminary_item_rejected"] in result.narrative_description
    assert "possessions remain unchanged" not in result.narrative_description
    assert "player" not in result.narrative_description.lower()
    assert result.updated_entities[0].inventory is None


@pytest.mark.parametrize("input_id", [None, "a-different-input"])
def test_unbound_or_stale_rejection_cannot_supply_reconciliation_authority(input_id):
    manager = continuity_manager()
    manager._vn_player_message_id = "rejected-input"
    prepare_intent(manager, {"removed_inventory_item_ids": ["NOT_CARRIED"]}, [])
    manager._vn_player_message_id = input_id
    assert current_rejection(manager) is None
    assert rejection_reason(manager, []) == "" and rejected_targets(manager, []) is None


@pytest.mark.parametrize(
    "authority,expected_blocked",
    [("text_only", False), ("current", True), ("previous_input", False), ("rules", True)],
)
async def test_reconciliation_gate_uses_current_host_rejection_instead_of_narrative_text(
    monkeypatch, authority, expected_blocked
):
    roles = TurnRoles()
    install_roles(monkeypatch, roles)
    reconcile = AsyncMock(return_value=[])
    monkeypatch.setattr(gameplay, "reconcile_items", reconcile)

    def prepare(manager, intent, entities, *, control=None, item_plan=None):
        result = prepare_intent(manager, intent, entities, control=control, item_plan=item_plan)
        if authority in {"current", "previous_input"}:
            result = prepare_intent(
                manager, {"removed_inventory_item_ids": ["NOT_CARRIED"]}, entities
            )
            if authority == "previous_input":
                manager._vn_item_rejection["input_id"] = "a-previous-input"
        result.narrative_description = (
            LEGACY_DENIAL
            if authority in {"text_only", "previous_input"}
            else "A differently worded preliminary result."
        )
        return result

    monkeypatch.setattr(gameplay, "prepare_intent", prepare)
    if authority == "rules":
        monkeypatch.setattr(
            gameplay.GameTurnManager,
            "_enforce_exit_unlock_guardrails",
            AsyncMock(return_value=["The door remains locked."]),
        )
    async with TestSessionLocal() as db:
        user, _, _, _ = await seed_vn(db)
        events = [
            event
            async for event in gameplay.GameTurnManager(db, "session-1", user).process_turn(
                "I wait."
            )
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
    reconcile.assert_awaited_once()
    supplied = reconcile.call_args.kwargs
    assert supplied["blocked"] is expected_blocked
    if authority == "current":
        assert supplied["blocked_reason"] == MESSAGES["preliminary_item_rejected"]
        assert {"NOT_CARRIED", "__player__"} <= supplied["blocked_targets"]
    elif authority == "rules":
        assert "The door remains locked." in supplied["blocked_reason"]
        assert supplied["blocked_targets"] is None
    else:
        assert supplied["blocked_reason"] == "" and supplied["blocked_targets"] is None


class PreliminaryKeyFailureRoles(EarlierFailureRoles):
    @staticmethod
    def commands():
        return [
            {"name": "take_item", "arguments": {"item_id": "BRASS_KEY"}},
            {
                "name": "give_item",
                "arguments": {"item_id": "BRASS_KEY", "recipient_id": "@player"},
            },
        ]

    async def simple(self, system, payload, model, **kwargs):
        if kwargs.get("phase") == "validation":
            self.review_payloads.append(json.loads(payload))
        return await ActionRoles.simple(self, system, payload, model, **kwargs)


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_failed_preliminary_inventory_and_later_key_commands_keep_distinct_authority(
    monkeypatch, protocol
):
    roles = PreliminaryKeyFailureRoles()
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await prepare_controlled(db, "integrated", protocol, False)
        kernel = load(state)
        kernel.settings.action_tools = True
        state.entity_states = {**state.entity_states, KEY: kernel.model_dump()}
        db.add(
            WorldEntity(
                id="BRASS_KEY",
                session_id=state.session_id,
                entity_type="OBJECT",
                name="Brass key",
                description="One ordinary brass key.",
                current_scene_id="START",
                is_hidden=False,
                is_in_inventory=False,
            )
        )
        await db.commit()
        manager, events = await run(db, user, "Lina, take the brass key and give it to me.")
        assert final_payload(events)["status"] == "success", "".join(events)
        assert len(roles.review_payloads) == 1
        reviewed = roles.review_payloads[0]
        assert "The preliminary item proposal was not applied." in reviewed["host_resolution"]
        assert MESSAGES["preliminary_item_rejected"] in reviewed["host_resolution"]
        assert "possessions remain unchanged" not in reviewed["host_resolution"]
        assert reviewed["host_resolution_time"] == "before_command_publication"
        outcomes = reviewed["contract"]["LINA"]["authoritative_command_outcomes"]
        assert [row["tool"] for row in outcomes] == ["take_item", "give_item"]
        assert [row["status"] for row in outcomes] == ["applied", "applied"]
        assert all(row["effect"]["item_id"] == "BRASS_KEY" for row in outcomes)
        assert roles.reconciliations[-1]["owners"]["BRASS_KEY"] == "__player__"
        assert roles.reconciliations[-1]["item_changes_allowed"] is False
        assert load(manager.state).usage.calls == 4
        await db.refresh(manager.avatar)
        assert [item["id"] for item in manager.avatar.inventory].count("BRASS_KEY") == 1
