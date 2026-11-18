"""Narration consumers share current owner facts without treating plans as outcomes."""

import json
from copy import deepcopy

import pytest
from sqlalchemy import delete, select, update

from backend.engine import turn_controls
from backend.engine.chpm import (
    continuation,
    inference,
    narration_repair_input,
    observable_state,
    rendering,
    runtime,
)
from backend.engine.chpm.errors import StaleControlError
from backend.engine.chpm.observable_state import capture as capture_views
from backend.engine.chpm.state import KEY, load
from backend.engine.clothing.visuals import session_objects
from backend.engine.npc_actions import execution_frame
from backend.engine.npc_actions.contracts import ChangeState, TakeOff
from backend.engine.npc_actions.control import model_outcomes
from backend.engine.npc_actions.preparation import capture as capture_actions
from backend.engine.npc_actions.publication import publish
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.npc_control_support import bind_observation
from tests.observable_state_support import world
from tests.test_chpm_compact_contract import contract_fixture
from tests.test_chpm_host_turn import run
from tests.test_chpm_kernel import observation
from tests.test_chpm_notebook_turn import ACTION, install
from tests.test_chpm_observable_turn import prepare
from tests.test_npc_action_empty_turn import EmptyPlanRoles
from tests.test_npc_action_publication import fixture


async def prepared(db):
    manager, observed, _ = await fixture(db)
    actor = await db.scalar(
        select(WorldEntity).where(
            WorldEntity.session_id == manager.game_id, WorldEntity.id == "LINA"
        )
    )
    actor.inventory = [
        {"id": "COAT", "name": "Coat", "clothing": {"layer": 2, "coverage": ["torso", "arms"]}},
        {"id": "PRIVATE_NOTE", "name": "A concealed note"},
    ]
    actor.visual_profile = {
        "appearance": {"age_years": 30},
        "worn": [{"item_id": "COAT", "uncovered_regions": ["arms"]}],
    }
    await db.flush()
    bind_observation(manager, observed)
    views = await capture_views(manager, ["LINA"], observed)
    draft = (await capture_actions(manager, views, observed))["LINA"]
    turn, _ = contract_fixture()
    selected = turn.decisions.pop("npc")
    selected = selected.model_copy(update={"actor_id": "LINA", "observation": observed})
    turn.decisions = {"LINA": selected}
    turn.minds = {}
    turn.names = {"LINA": "Lina"}
    turn.input_id = observed.message_id
    turn.action_drafts = {"LINA": draft}
    turn.control = turn_controls.scope(manager, "narration_review", observation=observed)
    return manager, observed, draft, turn


async def test_owner_coverage_wins_over_property_notes_in_all_existing_consumers():
    async with TestSessionLocal() as db:
        manager, observed, draft, turn = await prepared(db)
        assert (
            draft.execute(
                ChangeState(
                    tool="change_item_state",
                    item_id="COAT",
                    dimension="sleeves",
                    detail="The sleeves have been lowered.",
                )
            )["status"]
            == "staged"
        )
        draft.approved = True
        turn.action_outcomes = {"LINA": await publish(manager, draft)}
        turn.control = turn_controls.scope(manager, "narration_review", observation=observed)
        await execution_frame.capture(manager, turn, observed)
        before = deepcopy(turn.decisions["LINA"].model_dump())

        narrated = runtime.contract_data(turn)
        reviewed = rendering._review_payload(turn, {}, "The earlier host resolution.")["contract"]
        _, repair = narration_repair_input.build(
            turn,
            "Original policy",
            "Candidate",
            "The earlier host resolution.",
            [],
            portrait_reminder="",
        )

        assert narrated == reviewed == json.loads(repair)["dialogue_contract"]
        frame = narrated["current_execution_frame"]
        assert frame["entities"]["LINA"]["visible_clothing"][0]["uncovered_regions"] == ["arms"]
        note = frame["entities"]["COAT"]["recorded_conditions"][0]
        assert note["kind"] == "item_state" and note["meaning"] == "condition_note"
        assert frame["entities"]["KEY"]["owner_id"] == "__scene__"
        assert "PRIVATE_NOTE" not in str(frame)
        assert "intention" not in narrated["LINA"]
        assert (
            narrated["LINA"]["subjective_selected_intention_not_world_facts"] == before["selected"]
        )
        assert turn.decisions["LINA"].model_dump() == before
        assert turn.usage.calls == 0
        source = model_outcomes(turn)["LINA"][0]
        projected = narrated["LINA"]["authoritative_command_outcomes"][0]
        assert projected["request_control_ref"] == "/current_execution_frame/request_control"
        reconstructed = {
            key: value for key, value in projected.items() if key != "request_control_ref"
        }
        reconstructed.update(
            {
                key: value
                for key, value in frame["request_control"].items()
                if key in {"attempt_id", "input_id", "input_revision", "input_hash"}
            }
        )
        assert reconstructed == source


async def test_removed_known_garment_keeps_actual_owner_without_exposing_private_inventory():
    async with TestSessionLocal() as db:
        manager, observed, draft, turn = await prepared(db)
        assert draft.execute(TakeOff(tool="take_off_item", item_id="COAT"))["status"] == "staged"
        draft.approved = True
        turn.action_outcomes = {"LINA": await publish(manager, draft)}
        turn.control = turn_controls.scope(manager, "narration_review", observation=observed)
        await execution_frame.capture(manager, turn, observed)

        frame = runtime.contract_data(turn)["current_execution_frame"]
        assert frame["entities"]["COAT"]["owner_id"] == "LINA"
        assert frame["entities"]["COAT"]["wear_status"] == "not_worn"
        assert "spatial_position" not in frame["entities"]["COAT"]
        assert "PRIVATE_NOTE" not in str(frame)
        continuation.activate(turn, "review_unavailable")
        assert json.dumps(
            frame, ensure_ascii=False, separators=(",", ":")
        ) in continuation.contract(turn)


@pytest.mark.parametrize("change", ["state", "scene", "input", "attempt"])
async def test_a_frame_from_another_current_revision_is_rejected(change):
    async with TestSessionLocal() as db:
        manager, observed, draft, turn = await prepared(db)
        draft.approved = True
        turn.action_outcomes = {"LINA": await publish(manager, draft)}
        await execution_frame.capture(manager, turn, observed)
        if change == "state":
            manager.state.in_game_time += 1
        if change == "scene":
            manager.state.current_scene_id = "OTHER"
        if change == "input":
            manager._vn_player_message_id = "OTHER_INPUT"
        if change == "attempt":
            turn_controls.begin(manager)
        with pytest.raises(StaleControlError):
            await execution_frame.ensure_current(manager, turn)


async def test_uncached_legacy_contract_and_owner_state_remain_unchanged():
    async with TestSessionLocal() as db:
        manager, observed, _, turn = await prepared(db)
        before = deepcopy(manager.state.entity_states)
        contract = runtime.contract_data(turn)
        await execution_frame.capture(manager, turn, observed)
        assert runtime.contract_data(turn) == contract
        assert "current_execution_frame" not in contract
        assert contract["LINA"]["intention"]
        assert manager.state.entity_states == before
        assert await session_objects(db, manager.game_id)


def test_public_owner_projection_never_unions_private_inventories():
    manager, rows = world()
    view = observable_state.project(manager, rows, "__player__", observation(), own_facts=False)
    assert {"npc", "other", "KEY", "COAT", "OTHER_COAT", "PLAYER_COAT"} <= view.entities.keys()
    assert (
        not {
            "FLASK",
            "OTHER_BAG_SECRET",
            "PLAYER_BAG_SECRET",
            "LINING",
            "OTHER_INNER",
            "HIDDEN",
            "AWAY",
        }
        & view.entities.keys()
    )
    assert "PRIVATE_SCRIPT" not in str(view.entities)
    assert "PRIVATE_METADATA" not in str(view.entities)


async def test_unrelated_private_updates_do_not_invalidate_owner_dependencies():
    async with TestSessionLocal() as db:
        manager, observed, draft, turn = await prepared(db)
        draft.approved = True
        turn.action_outcomes = {"LINA": await publish(manager, draft)}
        await execution_frame.capture(manager, turn, observed)
        before = runtime.contract_data(turn)["current_execution_frame"]
        manager.state.entity_states = {
            **manager.state.entity_states,
            "__unrelated_private_analysis__": {"status": "retained privately"},
        }
        await execution_frame.ensure_current(manager, turn)
        copied = runtime.contract_data(turn)["current_execution_frame"]
        copied["entities"]["KEY"]["owner_id"] = "invented"
        assert runtime.contract_data(turn)["current_execution_frame"] == before


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_real_turn_reuses_one_current_projection_in_review_and_repair(monkeypatch, protocol):
    roles = EmptyPlanRoles(repair=True)
    install(monkeypatch, roles)
    request = inference.request

    async def outside_transaction(
        manager, settings, usage, instruction, payload, schema, phase, **options
    ):
        if phase == "validation":
            assert not manager.db.in_transaction()
        return await request(
            manager, settings, usage, instruction, payload, schema, phase, **options
        )

    monkeypatch.setattr(inference, "request", outside_transaction)
    async with TestSessionLocal() as db:
        user, state = await prepare(db, "integrated", protocol, False)
        kernel = load(state)
        kernel.settings.action_tools = True
        state.entity_states = {**state.entity_states, KEY: kernel.model_dump()}
        await db.commit()
        _, events = await run(db, user, ACTION)
        assert any(event.startswith("event: final") for event in events), "".join(events)
        first = roles.reviews[0][1]["contract"]
        frame = first["current_execution_frame"]
        assert frame["scene_id"] == "START"
        assert frame["request_control"]["input_id"]
        assert all(record[1]["contract"] == first for record in roles.reviews)
        assert roles.repairs[0][1]["dialogue_contract"] == first
        assert json.dumps(frame, ensure_ascii=False, separators=(",", ":")) in str(roles.prompts)


@pytest.mark.parametrize("change", ["update", "delete"])
async def test_review_refreshes_sql_owners_instead_of_trusting_identity_map(monkeypatch, change):
    async with TestSessionLocal() as db:
        manager, observed, draft, turn = await prepared(db)
        draft.approved = True
        turn.action_outcomes = {"LINA": await publish(manager, draft)}
        await execution_frame.capture(manager, turn, observed)
        manager._chpm_turn = turn
        statement = (
            delete(WorldEntity)
            if change == "delete"
            else update(WorldEntity).values(is_hidden=True)
        )
        await db.execute(
            statement.where(
                WorldEntity.session_id == manager.game_id, WorldEntity.id == "KEY"
            ).execution_options(synchronize_session=False)
        )

        async def unexpected(*args, **kwargs):
            pytest.fail("Stale owner facts must be rejected before another model request.")

        monkeypatch.setattr(inference, "request", unexpected)
        with pytest.raises(StaleControlError, match="Current owner facts changed"):
            await rendering._review(manager, turn, 'Lina: "I will wait."', "")


@pytest.mark.parametrize("field", ["attempt_id", "input_id", "input_revision", "input_hash"])
async def test_shared_binding_reference_cannot_hide_mismatched_operation_metadata(field):
    async with TestSessionLocal() as db:
        manager, observed, draft, turn = await prepared(db)
        assert draft.execute(TakeOff(tool="take_off_item", item_id="COAT"))["status"] == "staged"
        draft.approved = True
        turn.action_outcomes = {"LINA": await publish(manager, draft)}
        turn.control = turn_controls.scope(manager, "narration_review", observation=observed)
        await execution_frame.capture(manager, turn, observed)
        record = deepcopy(model_outcomes(turn)["LINA"][0])
        record[field] = "another_source"
        with pytest.raises(StaleControlError, match="shared execution frame binding"):
            execution_frame.records(turn, [record])
