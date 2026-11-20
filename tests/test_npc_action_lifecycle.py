"""Source and controller freshness, current policy, limits and real session copies."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.sessions import copy_session
from backend.engine.chpm.observable_state import capture as capture_views
from backend.engine.chpm.schema import KernelState, Settings
from backend.engine.chpm.state import KEY
from backend.engine.npc_actions.contracts import ChangeState, Discard, Move, PutDown, Wear
from backend.engine.npc_actions.preparation import capture as capture_actions
from backend.engine.npc_actions.preview import MAX_ACTIONS
from backend.engine.npc_actions.publication import publish
from backend.engine.npc_actions.runtime import publish_turn
from backend.engine.physical_conditions.ledger import read
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.test_npc_action_movement import movement_fixture


def controller_turn(manager, observed, draft):
    initial = KernelState(
        settings=Settings(
            mode="live", workflow="integrated", action_tools=True, actor_ids=["LINA"], agent_steps=2
        )
    )
    manager.state.entity_states = {**manager.state.entity_states, KEY: initial.model_dump()}
    draft.approved = True
    return SimpleNamespace(
        initial=initial,
        input_id=observed.message_id,
        action_drafts={"LINA": draft},
        action_outcomes={},
        decisions={"LINA": SimpleNamespace(observation=observed)},
        simplified=False,
    )


@pytest.mark.parametrize("change", ["contents", "revision", "role", "active_input"])
async def test_changed_saved_source_never_publishes_an_approved_plan(change):
    async with TestSessionLocal() as db:
        manager, _, _, observed, draft = await movement_fixture(db)
        assert (
            draft.execute(Move(tool="move_to", destination_scene_id="ANNEX"))["status"] == "staged"
        )
        current = controller_turn(manager, observed, draft)
        message = await db.get(ChatMessage, observed.message_id)
        if change == "contents":
            message.content += " A changed instruction."
        elif change == "revision":
            message.revision_id = "changed-revision"
        elif change == "role":
            message.role = "assistant"
        else:
            manager._vn_player_message_id = "another-input"
        await publish_turn(manager, current)
        assert current.action_outcomes["LINA"][0]["status"] == "stale"
        assert (
            manager.state.entity_states.get("LINA", {}).get("current_scene_id", "START") == "START"
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"mode": "off"},
        {"action_tools": False},
        {"actor_ids": ["OTHER"]},
        {"max_input_chars": 48000},
    ],
)
async def test_changed_controller_settings_never_publish_an_older_approved_plan(changes):
    async with TestSessionLocal() as db:
        manager, _, _, observed, draft = await movement_fixture(db)
        assert (
            draft.execute(Move(tool="move_to", destination_scene_id="ANNEX"))["status"] == "staged"
        )
        current = controller_turn(manager, observed, draft)
        states = deepcopy(manager.state.entity_states)
        states[KEY]["settings"].update(changes)
        manager.state.entity_states = states
        await publish_turn(manager, current)
        assert current.action_outcomes["LINA"][0]["status"] == "stale"
        assert manager.state.current_scene_id == "START" and manager.state.in_game_time == 23


async def test_property_command_uses_current_game_minute_after_preparation():
    async with TestSessionLocal() as db:
        manager, _, _, _, draft = await movement_fixture(db)
        assert (
            draft.execute(
                ChangeState(
                    tool="change_item_state",
                    item_id="HIDDEN_RING",
                    dimension="surface",
                    detail="A polished surface.",
                )
            )["status"]
            == "staged"
        )
        manager.state.in_game_time = 41
        draft.approved = True
        assert (await publish(manager, draft))[0]["status"] == "applied"
        row = next(iter(read(manager.state.entity_states).conditions.values()))
        assert row.first_recorded_minute == row.last_changed_minute == 41
        assert manager.state.in_game_time == 41


async def test_detail_policy_disabled_after_staging_blocks_the_previous_wardrobe_preview():
    async with TestSessionLocal() as db:
        manager, actor, _, observed, _ = await movement_fixture(db)
        actor.visual_profile = {"version": 1, "appearance": {"age_years": 30}, "worn": []}
        actor.inventory = [
            *actor.inventory,
            {
                "id": "BASE_LAYER",
                "name": "Cotton base layer",
                "item_type": "WEARABLE",
                "wearable_slots": ["Chest"],
                "clothing": {"layer": 0, "coverage": ["torso"], "underwear": True},
            },
        ]
        manager.state.entity_states = {
            **manager.state.entity_states,
            "__manifest_snapshot__": {
                "original_manifest": {"clothing_settings": {"detailed": True}}
            },
        }
        await db.flush()
        views = await capture_views(manager, ["LINA"], observed)
        draft = (await capture_actions(manager, views, observed))["LINA"]
        assert draft.execute(Wear(tool="wear_item", item_id="BASE_LAYER"))["status"] == "staged"
        manager.state.entity_states = {
            **manager.state.entity_states,
            "__manifest_snapshot__": {
                "original_manifest": {"clothing_settings": {"detailed": False}}
            },
        }
        draft.approved = True
        assert (await publish(manager, draft))[0]["status"] == "blocked"
        assert not manager.state.entity_states.get("LINA", {}).get("visual_profile", {}).get("worn")


async def test_exact_plan_capacity_and_discard_do_not_publish_extra_or_abandoned_changes():
    async with TestSessionLocal() as db:
        manager, _, _, _, draft = await movement_fixture(db)
        for index in range(MAX_ACTIONS):
            result = draft.execute(
                ChangeState(
                    tool="change_item_state",
                    item_id="HIDDEN_RING",
                    dimension="surface",
                    detail=f"Surface revision {index}.",
                )
            )
            assert result["status"] == "staged"
        assert len(draft.requests) == MAX_ACTIONS
        assert (
            draft.execute(
                ChangeState(
                    tool="change_item_state",
                    item_id="HIDDEN_RING",
                    dimension="surface",
                    detail="Beyond the limit.",
                )
            )["status"]
            == "action_limit"
        )
        assert draft.execute(Discard(tool="discard_actions"))["status"] == "discarded"
        assert not draft.requests and not read(manager.state.entity_states).conditions
        assert (
            draft.execute(
                ChangeState(
                    tool="change_item_state",
                    item_id="HIDDEN_RING",
                    dimension="surface",
                    detail="The chosen final surface.",
                )
            )["status"]
            == "staged"
        )
        draft.approved = True
        assert len(await publish(manager, draft)) == 1
        ledger = read(manager.state.entity_states)
        assert len(ledger.conditions) == len(ledger.events) == 1
        assert next(iter(ledger.conditions.values())).detail == "The chosen final surface."


async def test_real_session_copy_keeps_command_facts_and_remaps_their_saved_input_anchor():
    async with TestSessionLocal() as db:
        manager, _, _, observed, draft = await movement_fixture(db)
        assert (
            draft.execute(
                ChangeState(
                    tool="change_item_state",
                    item_id="HIDDEN_RING",
                    dimension="surface",
                    detail="A polished surface.",
                )
            )["status"]
            == "staged"
        )
        assert (
            draft.execute(
                PutDown(tool="put_down_item", item_id="HIDDEN_RING", position="on the bench")
            )["status"]
            == "staged"
        )
        draft.approved = True
        assert [row["status"] for row in await publish(manager, draft)] == ["applied", "applied"]
        await db.commit()
        original = next(iter(read(manager.state.entity_states).conditions.values()))
        result = await copy_session(manager.game_id, db, manager.user)
        copied_state = await db.scalar(
            select(SessionState).where(SessionState.session_id == result["game_id"])
        )
        copied = read(copied_state.entity_states).conditions[original.id]
        assert copied.detail == original.detail and copied.target_id == "HIDDEN_RING"
        assert copied.latest.kind == "command" and copied.latest.command == original.latest.command
        assert copied.latest.message_id != observed.message_id
        copied_input = await db.get(ChatMessage, copied.latest.message_id)
        assert copied_input.session_id == copied_state.session_id and copied_input.role == "user"
        assert copied_state.in_game_time == manager.state.in_game_time == 23
        assert copied_state.entity_states["HIDDEN_RING"]["is_in_inventory"] is False
