"""Narrative receipts retain authority without exposing inaccessible item facts."""

import json
from copy import deepcopy

import pytest
from sqlalchemy import select

from backend.engine import turn_controls
from backend.engine.chpm import continuation, narration_repair_input, rendering, runtime
from backend.engine.narrated_items.schema import ItemExtraction
from backend.engine.npc_actions import execution_frame, outcome_projection, reconciliation
from backend.engine.npc_actions.contracts import ChangeState, PutDown
from backend.engine.npc_actions.control import CommandRejectedError, model_outcomes
from backend.engine.npc_actions.publication import publish
from backend.engine.physical_conditions.ledger import read
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_npc_execution_frame import prepared

DETAIL = "The reserve inscription reads amber-seven."
PROPERTY_FIELDS = {"dimension", "detail", "condition_id"}


async def publish_property(db, *, visibility="private", item_id="COAT", covered=False):
    manager, observed, draft, turn = await prepared(db)
    request = ChangeState(
        tool="change_item_state",
        item_id=item_id,
        dimension="inscription",
        detail=DETAIL,
        visibility=visibility,
    )
    assert draft.execute(request)["status"] == "staged"
    if covered:
        actor = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == manager.game_id, WorldEntity.id == "LINA"
            )
        )
        actor.inventory = [
            *actor.inventory,
            {
                "id": "OUTER",
                "name": "Outer coat",
                "clothing": {"layer": 3, "coverage": ["torso", "arms"]},
            },
        ]
        actor.visual_profile = {
            "appearance": {"age_years": 30},
            "worn": [{"item_id": "COAT"}, {"item_id": "OUTER"}],
        }
        await db.flush()
    draft.approved = True
    turn.action_outcomes = {"LINA": await publish(manager, draft)}
    turn.control = turn_controls.scope(manager, "narration_review", observation=observed)
    await execution_frame.capture(manager, turn, observed)
    assert turn.action_outcomes["LINA"][0]["status"] == "applied"
    return manager, observed, draft, turn


def narrative_consumers(turn):
    narrated = runtime.contract_data(turn)
    reviewed = rendering._review_payload(turn, {}, "Earlier resolution")["contract"]
    _, repair = narration_repair_input.build(
        turn, "Original policy", "Candidate", "Earlier resolution", [], portrait_reminder=""
    )
    repaired = json.loads(repair)["dialogue_contract"]
    fallback = deepcopy(turn)
    continuation.activate(fallback, "review_unavailable")
    continuation_text = continuation.contract(fallback)
    continued = json.loads(continuation_text[continuation_text.index("{") :])
    return [
        narrated["LINA"]["authoritative_command_outcomes"],
        reviewed["LINA"]["authoritative_command_outcomes"],
        repaired["LINA"]["authoritative_command_outcomes"],
        continued["authoritative_command_outcomes"]["LINA"],
    ]


def assert_metadata(projected, source):
    shared = {"attempt_id", "input_id", "input_revision", "input_hash"}
    for key, value in source.items():
        if key not in shared | {"effect"}:
            assert projected[key] == value


@pytest.mark.parametrize("visibility,covered", [("private", False), ("public", True)])
async def test_private_and_covered_properties_are_omitted_from_all_narrative_consumers(
    visibility, covered
):
    async with TestSessionLocal() as db:
        manager, _, _, turn = await publish_property(db, visibility=visibility, covered=covered)
        original = deepcopy(turn.action_outcomes)
        condition = next(iter(read(manager.state.entity_states).conditions.values()))
        assert condition.visibility == visibility and condition.detail == DETAIL
        assert "COAT" in turn.execution_frame.entities
        for records in narrative_consumers(turn):
            record = records[0]
            assert record["effect"] == {"item_id": "COAT"}
            assert set(record["effect_omitted"]["fields"]) == PROPERTY_FIELDS
            assert DETAIL not in json.dumps(record)
            assert_metadata(record, original["LINA"][0])
        assert turn.action_outcomes == model_outcomes(turn) == original


async def test_visible_public_property_remains_exact_and_does_not_alias_host_receipts():
    async with TestSessionLocal() as db:
        _, _, _, turn = await publish_property(db, visibility="public")
        original = deepcopy(turn.action_outcomes)
        for records in narrative_consumers(turn):
            assert records[0]["effect"] == original["LINA"][0]["effect"]
            assert "effect_omitted" not in records[0]
            assert_metadata(records[0], original["LINA"][0])
        projected = runtime.contract_data(turn)["LINA"]["authoritative_command_outcomes"][0]
        projected["effect"]["detail"] = "A fabricated replacement."
        assert turn.action_outcomes == original


async def test_hidden_target_omits_identity_and_description_without_losing_applied_status():
    async with TestSessionLocal() as db:
        _, _, _, turn = await publish_property(db, item_id="PRIVATE_NOTE")
        original = deepcopy(turn.action_outcomes)
        assert "PRIVATE_NOTE" not in turn.execution_frame.entities
        for records in narrative_consumers(turn):
            record = records[0]
            assert record["effect"] == {}
            assert set(record["effect_omitted"]["fields"]) == {"item_id", *PROPERTY_FIELDS}
            assert "PRIVATE_NOTE" not in json.dumps(record)
            assert DETAIL not in json.dumps(record)
            assert_metadata(record, original["LINA"][0])
        assert turn.action_outcomes == original


async def test_missing_public_frame_fails_closed_including_ordinary_continuation():
    async with TestSessionLocal() as db:
        _, _, _, turn = await publish_property(db, visibility="public")
        original = deepcopy(turn.action_outcomes)
        turn.execution_frame = None
        for records in narrative_consumers(turn):
            record = records[0]
            assert record["effect"] == {}
            assert record["effect_omitted"]["reason"] == "public_view_unavailable"
            assert_metadata(record, original["LINA"][0])
            assert record["attempt_id"] == original["LINA"][0]["attempt_id"]
        assert turn.action_outcomes == original


async def test_later_property_value_does_not_relabel_the_earlier_public_event():
    async with TestSessionLocal() as db:
        manager, observed, draft, turn = await prepared(db)
        for detail in (DETAIL, "The reserve inscription is covered with a blank patch."):
            assert (
                draft.execute(
                    ChangeState(
                        tool="change_item_state",
                        item_id="COAT",
                        dimension="inscription",
                        detail=detail,
                    )
                )["status"]
                == "staged"
            )
        draft.approved = True
        turn.action_outcomes = {"LINA": await publish(manager, draft)}
        turn.control = turn_controls.scope(manager, "narration_review", observation=observed)
        await execution_frame.capture(manager, turn, observed)
        original = deepcopy(turn.action_outcomes)
        for first, last in narrative_consumers(turn):
            assert first["effect"] == {"item_id": "COAT"}
            assert set(first["effect_omitted"]["fields"]) == PROPERTY_FIELDS
            assert last["effect"] == original["LINA"][-1]["effect"]
        assert turn.action_outcomes == original


@pytest.mark.parametrize("field", ["condition_id", "dimension", "detail"])
async def test_public_property_requires_the_exact_owner_condition_and_value(field):
    async with TestSessionLocal() as db:
        _, _, _, turn = await publish_property(db, visibility="public")
        original = deepcopy(turn.action_outcomes)
        candidate = deepcopy(original["LINA"][0])
        candidate["effect"][field] = "another_value"
        projected = outcome_projection.project(candidate, turn.execution_frame.entities)
        assert projected["effect"] == {"item_id": "COAT"}
        assert set(projected["effect_omitted"]["fields"]) == PROPERTY_FIELDS
        assert turn.action_outcomes == original


async def test_private_property_does_not_suppress_an_independent_public_transfer():
    async with TestSessionLocal() as db:
        manager, observed, draft, turn = await prepared(db)
        assert (
            draft.execute(
                ChangeState(
                    tool="change_item_state",
                    item_id="COAT",
                    dimension="inscription",
                    detail=DETAIL,
                    visibility="private",
                )
            )["status"]
            == "staged"
        )
        assert (
            draft.execute(
                PutDown(tool="put_down_item", item_id="PRIVATE_NOTE", position="on the desk")
            )["status"]
            == "staged"
        )
        draft.approved = True
        turn.action_outcomes = {"LINA": await publish(manager, draft)}
        turn.control = turn_controls.scope(manager, "narration_review", observation=observed)
        await execution_frame.capture(manager, turn, observed)
        original = deepcopy(turn.action_outcomes)
        for private, transfer in narrative_consumers(turn):
            assert PROPERTY_FIELDS.isdisjoint(private["effect"])
            assert transfer["effect"] == original["LINA"][1]["effect"]
            assert "effect_omitted" not in transfer
        assert turn.action_outcomes == original


@pytest.mark.parametrize("field", ["attempt_id", "input_id", "input_hash", "operation_id"])
async def test_invalid_private_receipts_are_rejected_before_visibility_projection(field):
    async with TestSessionLocal() as db:
        _, _, _, turn = await publish_property(db)
        turn.action_outcomes["LINA"][0][field] = "another_source"
        with pytest.raises(CommandRejectedError, match="operation"):
            runtime.contract_data(turn)


async def test_narrative_redaction_preserves_host_private_dimension_protection():
    async with TestSessionLocal() as db:
        manager, _, _, turn = await publish_property(db)
        turn.initial.settings = turn.initial.settings.model_copy(
            update={"mode": "live", "action_tools": True}
        )
        manager._chpm_turn = turn
        original = deepcopy(turn.action_outcomes)
        runtime.contract_data(turn)
        control = reconciliation.context(manager)
        assert control["outcomes"] == original
        extraction = ItemExtraction.model_validate(
            {
                "condition_updates": [
                    {
                        "operation": "change",
                        "condition_id": original["LINA"][0]["effect"]["condition_id"],
                        "detail": "A fabricated replacement.",
                        "evidence": "A fabricated replacement.",
                    }
                ]
            }
        )
        protected, _, errors = reconciliation.protect(manager, extraction)
        assert protected.condition_updates == []
        assert len(errors) == 1
        assert turn.action_outcomes == original
        assert next(iter(read(manager.state.entity_states).conditions.values())).detail == DETAIL


async def test_no_outcome_legacy_contract_never_requests_a_receipt_projection(monkeypatch):
    async with TestSessionLocal() as db:
        _, _, _, turn = await prepared(db)
        original = runtime.contract(turn)
        fallback = continuation.contract(turn)

        def unexpected(*_args, **_kwargs):
            pytest.fail("An absent command outcome must retain the existing narrative contract.")

        monkeypatch.setattr(outcome_projection, "project", unexpected)
        assert runtime.contract(turn) == original
        assert continuation.contract(turn) == fallback
