"""Typed preliminary denials localize unrelated state without granting custody."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.engine.chpm.state import KEY, load
from backend.engine.clothing.visuals import session_objects
from backend.engine.narrated_items.schema import ItemExtraction
from backend.engine.physical_conditions.ledger import read
from backend.engine.visual_novel.continuity import possession_snapshot
from backend.engine.visual_novel.item_rejections import _targets
from backend.engine.visual_novel.player_item_contracts import PlayerItemAction
from backend.models.avatar import Avatar
from tests.conftest import TestSessionLocal
from tests.state_response_fixture import extraction
from tests.test_chpm_action_turn import STATE
from tests.test_chpm_host_turn import run
from tests.test_chpm_notebook_turn import ACTION, install
from tests.test_chpm_observable_turn import DETAIL, StateRoles, prepare
from tests.test_npc_command_resolution_turn import EarlierFailureRoles
from tests.test_vn_player_item_operations import action
from tests.test_vn_turn_integration import NARRATION, final_payload

POT = "PAINT_POT"
OWNERS = {POT: "__player__", "RING": "LINA", "OTHER": "MIKI"}
PARTICIPANTS = {"__player__", "LINA", "MIKI"}
CONTAINERS = {"EMPTY_CONTAINER"}
INK = "The ring has a blue ink stain on its surface."


class LocalDenialRoles(StateRoles):
    async def structured(self, *args, **kwargs):
        schema = kwargs.get("response_model") or args[2]
        if schema.__name__.startswith("VNProgressionIntent"):
            self.calls.append((schema.__name__, args, kwargs))
            return schema(player_item_actions=[action("take", item_id=POT)])
        if issubclass(schema, ItemExtraction):
            self.calls.append((schema.__name__, args, kwargs))
            supplied = json.loads(args[1])
            self.reconciliations.append(supplied)
            updates = (
                [
                    {
                        "operation": "record",
                        "target_id": "HIDDEN_RING",
                        "kind": "item_state",
                        "part": "surface",
                        "detail": INK,
                        "evidence": INK,
                    }
                ]
                if supplied["independent_state_scope"] is not None
                else []
            )
            return extraction(schema, condition_updates=updates)
        return await super().structured(*args, **kwargs)


class UnknownDenialRoles(EarlierFailureRoles):
    async def structured(self, *args, **kwargs):
        schema = kwargs.get("response_model") or args[2]
        if schema.__name__.startswith("VNProgressionIntent"):
            self.calls.append((schema.__name__, args, kwargs))
            return schema(player_item_actions=[action("take", item_id="UNKNOWN")])
        return await super().structured(*args, **kwargs)


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_typed_duplicate_take_keeps_independent_condition_and_original_items(
    monkeypatch, protocol
):
    roles = LocalDenialRoles()
    install(monkeypatch, roles)
    monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", NARRATION + " " + INK)
    async with TestSessionLocal() as db:
        user, state = await prepare(db, "integrated", protocol, False)
        kernel = load(state)
        kernel.settings.action_tools = True
        state.entity_states = {**state.entity_states, KEY: kernel.model_dump()}
        avatar = await db.scalar(select(Avatar).where(Avatar.id == state.avatar_id))
        avatar.inventory = [{"id": POT, "name": "Reusable paint pot", "custom": {"keep": True}}]
        before_inventory = deepcopy(avatar.inventory)
        before = read(state.entity_states)
        await db.commit()

        manager, events = await run(db, user, ACTION)

        final = final_payload(events)
        assert final["status"] == "success", "".join(events)
        denial = manager._vn_item_rejection
        assert denial["input_id"] == final["saved_user_message_id"]
        assert denial["phase"] == "preliminary_items" and denial["status"] == "blocked"
        assert {"__player__", POT} <= set(denial["targets"])
        assert "LINA" not in denial["targets"] and "HIDDEN_RING" not in denial["targets"]
        supplied = roles.reconciliations[-1]
        assert supplied["item_changes_allowed"] is False
        assert {"__player__", POT, "START"} <= set(
            supplied["independent_state_scope"]["blocked_subject_ids"]
        )
        assert supplied["owners"][POT] == "__player__"
        assert supplied["owners"]["HIDDEN_RING"] == "LINA"
        await db.refresh(state)
        await db.refresh(avatar)
        assert avatar.inventory == before_inventory
        saved = read(state.entity_states)
        assert any(row.part == "surface" and row.detail == INK for row in saved.conditions.values())
        old_id = next(iter(before.conditions))
        assert saved.conditions[old_id] == before.conditions[old_id]
        assert saved.conditions[old_id].detail == DETAIL
        assert saved.last_check["status"] == "complete"
        assert len(saved.last_check["accepted"]) == 1 and not saved.last_check["rejected"]
        assert load(state).usage.calls == 4
        assert len(roles.reconciliations) == 1


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_unknown_typed_scope_blocks_shared_extraction_but_not_later_owned_commands(
    monkeypatch, protocol
):
    roles = UnknownDenialRoles()
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await prepare(db, "integrated", protocol, False)
        kernel = load(state)
        kernel.settings.action_tools = True
        state.entity_states = {**state.entity_states, KEY: kernel.model_dump()}
        before = read(state.entity_states)
        await db.commit()

        manager, events = await run(db, user, ACTION)

        assert final_payload(events)["status"] == "success", "".join(events)
        assert manager._vn_item_rejection["targets"] == []
        assert not roles.reconciliations
        assert not any(name == "SharedItemExtraction" for name, *_ in roles.calls)
        assert len(roles.calls) == 1
        reviewed = roles.review_payloads[-1]["contract"]["LINA"]["authoritative_command_outcomes"]
        assert [row["status"] for row in reviewed] == ["applied", "applied"]
        await db.refresh(state)
        current = possession_snapshot(manager, await session_objects(db, manager.game_id))
        assert current.owners["HIDDEN_RING"] == "__scene__"
        saved = read(state.entity_states)
        assert saved.conditions[next(iter(before.conditions))] == next(
            iter(before.conditions.values())
        )
        assert any(
            row.part == "surface" and row.detail == STATE for row in saved.conditions.values()
        )
        assert load(state).usage.calls == 4


def proposal(raw):
    return SimpleNamespace(player_item_actions=[raw])


@pytest.mark.parametrize(
    "operation,expected",
    [
        (action("take", item_id=POT), {"__player__", POT}),
        (action("give", item_id=POT, target_id="LINA"), {"__player__", POT, "LINA", "RING"}),
        (
            action("wear", item_id="RING", target_id="LINA"),
            {"__player__", POT, "LINA", "RING"},
        ),
        (
            action("give", item_id=POT, target_id="EMPTY_CONTAINER"),
            {"__player__", POT, "EMPTY_CONTAINER"},
        ),
        (
            action("acquire_garment", item_id=None, creation_ref=0, target_id="LINA"),
            {"__player__", POT, "LINA", "RING"},
        ),
    ],
)
def test_typed_denial_contains_each_known_participant_and_its_current_possessions(
    operation, expected
):
    intent = proposal(PlayerItemAction.model_validate(operation))
    assert _targets(intent, OWNERS, participants=PARTICIPANTS, containers=CONTAINERS) == expected


@pytest.mark.parametrize(
    "raw",
    [
        action("take", item_id="UNKNOWN"),
        action("take", item_id=POT, performer_id=None),
        action("take", item_id=POT, performer_id="UNKNOWN"),
        action("take", item_id=POT, performer_id="__player__ "),
        action("give", item_id=POT, target_id="UNKNOWN"),
        action("give", item_id=POT, target_id=None),
        {"operation": "take", "item_id": POT},
        "not-an-action",
    ],
)
def test_unresolved_or_malformed_typed_denial_cannot_admit_independent_state(raw):
    intent = proposal(raw)
    intent.removed_inventory_item_ids = [POT]
    assert _targets(intent, OWNERS, participants=PARTICIPANTS) == set()


def test_mixed_legacy_and_typed_denial_keeps_both_ownership_scopes():
    intent = proposal(PlayerItemAction.model_validate(action("take", item_id=POT)))
    intent.removed_inventory_item_ids = ["OTHER"]
    assert _targets(intent, OWNERS, participants=PARTICIPANTS) == {
        "__player__",
        POT,
        "MIKI",
        "OTHER",
    }


@pytest.mark.parametrize("performer", ["__scene__", "EMPTY_CONTAINER"])
def test_scene_and_container_handles_cannot_localize_a_character_performer(performer):
    owners = {**OWNERS, "CONTENTS": "EMPTY_CONTAINER", "TABLE_ITEM": "__scene__"}
    intent = proposal(action("take", item_id=POT, performer_id=performer))
    assert (
        _targets(intent, owners, participants=PARTICIPANTS - {"EMPTY_CONTAINER", "__scene__"})
        == set()
    )


@pytest.mark.parametrize("actions", [{}, "", False, [action("take", item_id=POT)] * 7])
def test_unusable_typed_batch_cannot_borrow_locality_from_legacy_fields(actions):
    intent = SimpleNamespace(player_item_actions=actions, removed_inventory_item_ids=[POT])
    assert _targets(intent, OWNERS, participants=PARTICIPANTS) == set()


def test_missing_possession_snapshot_cannot_grant_locality_to_a_typed_denial():
    intent = proposal(action("take", item_id=POT))
    assert _targets(intent, OWNERS) == set()


@pytest.mark.parametrize("operation", ["wear", "remove", "adjust", "acquire_garment"])
def test_wardrobe_target_must_be_a_character_even_when_container_is_known(operation):
    raw = action(operation, item_id=POT, target_id="EMPTY_CONTAINER")
    if operation == "acquire_garment":
        raw.update(item_id=None, creation_ref=0)
    assert (
        _targets(proposal(raw), OWNERS, participants=PARTICIPANTS, containers=CONTAINERS) == set()
    )


@pytest.mark.parametrize("operation", ["take", "drop", "consume", "destroy"])
def test_operations_without_recipient_cannot_borrow_locality_from_one(operation):
    raw = action(operation, item_id=POT, target_id="LINA")
    assert (
        _targets(proposal(raw), OWNERS, participants=PARTICIPANTS, containers=CONTAINERS) == set()
    )
