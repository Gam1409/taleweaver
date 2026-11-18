"""Public execution views stay scoped and bounded as canonical state accumulates."""

import json
from copy import deepcopy

import pytest

from backend.engine import turn_controls
from backend.engine.chpm import narration_repair_input, rendering, runtime
from backend.engine.chpm.errors import StaleControlError
from backend.engine.npc_actions import execution_frame
from backend.engine.npc_actions.contracts import ChangeState, Give, Take
from backend.engine.npc_actions.publication import publish
from backend.engine.physical_conditions.command_source import CommandProof
from backend.engine.physical_conditions.item_commands import apply_command
from backend.engine.physical_conditions.ledger import read
from tests.conftest import TestSessionLocal
from tests.test_npc_execution_frame import prepared


def background(manager, observed, count=32):
    for index in range(count):
        manager.state.entity_states, _ = apply_command(
            manager.state.entity_states,
            item_id="COAT",
            dimension=f"mark_{index}",
            detail=(f"Mark {index}: " + "A pale line runs along the woven material. " * 8)[:300],
            owned_item_ids={"COAT"},
            proof=CommandProof(
                id=f"prior_command_{index}", actor_id="LINA", operation="change_item_state"
            ),
            message_id=observed.message_id,
            request_hash=f"{index:064x}",
            session_id=manager.game_id,
            minute=observed.minute,
            visibility="public",
        )


async def publish_frame(manager, observed, draft, turn):
    draft.approved = True
    turn.action_outcomes = {"LINA": await publish(manager, draft)}
    turn.control = turn_controls.scope(manager, "narration_review", observation=observed)
    await execution_frame.capture(manager, turn, observed)
    return runtime.contract_data(turn)["current_execution_frame"]


@pytest.mark.parametrize("visibility", ["public", "private"])
async def test_chosen_private_item_command_does_not_create_public_identity(visibility):
    async with TestSessionLocal() as db:
        manager, observed, draft, turn = await prepared(db)
        assert (
            draft.execute(
                ChangeState(
                    tool="change_item_state",
                    item_id="PRIVATE_NOTE",
                    dimension="fold",
                    detail="The concealed note is folded inward.",
                    visibility=visibility,
                )
            )["status"]
            == "staged"
        )
        frame = await publish_frame(manager, observed, draft, turn)
        assert "PRIVATE_NOTE" not in frame["entities"]
        assert "PRIVATE_NOTE" not in json.dumps(frame)
        assert turn.action_outcomes["LINA"][0]["status"] == "applied"
        record = next(iter(read(manager.state.entity_states).conditions.values()))
        assert record.target_id == "PRIVATE_NOTE" and record.visibility == visibility


async def test_accumulated_background_notes_do_not_exhaust_the_existing_review_budget():
    async with TestSessionLocal() as db:
        manager, observed, draft, turn = await prepared(db)
        turn.initial.settings = turn.initial.settings.model_copy(
            update={"mode": "live", "actor_ids": ["LINA"], "max_input_chars": 24000}
        )
        background(manager, observed)
        before = deepcopy(read(manager.state.entity_states).model_dump())
        frame = await publish_frame(manager, observed, draft, turn)
        rendering.preflight(turn)
        assert rendering._review_room(turn) >= 3072
        assert turn.reply_character_budget >= 512
        assert turn.initial.settings.max_input_chars == 24000
        visible = frame["entities"]["COAT"]
        omitted = visible["omitted_recorded_conditions"]
        assert omitted > 0 and len(visible["recorded_conditions"]) + omitted == 32
        assert frame["omitted_background_conditions"] == omitted
        assert frame["recorded_conditions_are_exhaustive"] is False
        assert frame["entities"]["LINA"]["visible_clothing"][0]["uncovered_regions"] == ["arms"]
        assert frame["entities"]["KEY"]["owner_id"] == "__scene__"
        reviewed = rendering._review_payload(turn, {}, "")["contract"]["current_execution_frame"]
        _, repaired = narration_repair_input.build(
            turn, "Original policy", "Candidate", "", [], portrait_reminder=""
        )
        assert reviewed == frame
        assert json.loads(repaired)["dialogue_contract"]["current_execution_frame"] == frame
        assert read(manager.state.entity_states).model_dump() == before
        assert turn.usage.calls == 0


async def test_current_command_condition_survives_full_optional_background():
    async with TestSessionLocal() as db:
        manager, observed, draft, turn = await prepared(db)
        background(manager, observed)
        detail = "The current label is firmly attached, with a clear square mark."
        assert (
            draft.execute(
                ChangeState(
                    tool="change_item_state",
                    item_id="COAT",
                    dimension="current_label",
                    detail=detail,
                )
            )["status"]
            == "staged"
        )
        frame = await publish_frame(manager, observed, draft, turn)
        condition_id = turn.action_outcomes["LINA"][0]["effect"]["condition_id"]
        condition = next(
            record
            for record in frame["entities"]["COAT"]["recorded_conditions"]
            if record["id"] == condition_id
        )
        assert condition["detail"] == detail and condition["status"] == "active"
        assert len(read(manager.state.entity_states).conditions) == 33
        assert frame["entities"]["COAT"]["omitted_recorded_conditions"] > 0


async def test_optional_budget_never_truncates_a_large_current_command_set():
    async with TestSessionLocal() as db:
        manager, observed, draft, turn = await prepared(db)
        background(manager, observed)
        for index in range(6):
            assert (
                draft.execute(
                    ChangeState(
                        tool="change_item_state",
                        item_id="COAT",
                        dimension=f"current_{index}",
                        detail=(f"Current mark {index}. " + "A clearly recorded seam. " * 16)[:300],
                    )
                )["status"]
                == "staged"
            )
        frame = await publish_frame(manager, observed, draft, turn)
        required = {record["effect"]["condition_id"] for record in turn.action_outcomes["LINA"]}
        conditions = frame["entities"]["COAT"]["recorded_conditions"]
        assert required <= {record["id"] for record in conditions}
        optional = [record for record in conditions if record["id"] not in required]
        assert (
            sum(
                len(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
                for record in optional
            )
            <= execution_frame.BACKGROUND_CONDITION_CHARS
        )
        assert len(read(manager.state.entity_states).conditions) == 38


async def test_omitted_background_remains_an_owner_freshness_dependency():
    async with TestSessionLocal() as db:
        manager, observed, draft, turn = await prepared(db)
        background(manager, observed)
        frame = await publish_frame(manager, observed, draft, turn)
        shown = {record["id"] for record in frame["entities"]["COAT"]["recorded_conditions"]}
        omitted = next(
            record
            for record in read(manager.state.entity_states).conditions.values()
            if record.id not in shown
        )
        manager.state.entity_states, _ = apply_command(
            manager.state.entity_states,
            item_id="COAT",
            dimension=omitted.part,
            detail="This omitted background note changed under its existing owner.",
            owned_item_ids={"COAT"},
            proof=CommandProof(
                id="changed_background", actor_id="LINA", operation="change_item_state"
            ),
            message_id=observed.message_id,
            request_hash="a" * 64,
            session_id=manager.game_id,
            minute=observed.minute,
            visibility="public",
        )
        with pytest.raises(StaleControlError, match="Current owner facts changed"):
            await execution_frame.ensure_current(manager, turn)


async def test_a_previously_public_object_keeps_current_custody_after_pickup():
    async with TestSessionLocal() as db:
        manager, observed, draft, turn = await prepared(db)
        assert draft.execute(Take(tool="take_item", item_id="KEY"))["status"] == "staged"
        frame = await publish_frame(manager, observed, draft, turn)
        assert frame["entities"]["KEY"]["owner_id"] == "LINA"
        assert frame["entities"]["KEY"]["wear_status"] == "not_worn"


async def test_public_owner_receipts_survive_narrator_review_and_repair_chronology():
    async with TestSessionLocal() as db:
        manager, observed, draft, turn = await prepared(db)
        for request in (
            Take(tool="take_item", item_id="KEY"),
            Give(tool="give_item", item_id="KEY", recipient_id="@player"),
        ):
            assert draft.execute(request)["status"] == "staged"
        frame = await publish_frame(manager, observed, draft, turn)
        canonical = deepcopy(turn.action_outcomes)
        assert frame["entities"]["KEY"]["owner_id"] == "@player"
        contract = runtime.contract_data(turn)
        resolution = "An earlier unrelated door check failed; the door stayed locked."
        reviewed = rendering._review_payload(turn, {}, resolution)
        _, repaired = narration_repair_input.build(
            turn, "Original policy", "Candidate", resolution, [], portrait_reminder=""
        )
        repaired = json.loads(repaired)
        assert reviewed["host_resolution"] == repaired["host_resolution"] == resolution
        assert (
            reviewed["host_resolution_time"]
            == repaired["host_resolution_time"]
            == "before_command_publication"
        )
        assert reviewed["contract"] == repaired["dialogue_contract"] == contract
        receipts = contract["LINA"]["authoritative_command_outcomes"]
        assert [receipt["status"] for receipt in receipts] == ["applied", "applied"]
        assert [receipt["tool"] for receipt in receipts] == ["take_item", "give_item"]
        assert [receipt["effect"] for receipt in receipts] == [
            receipt["effect"] for receipt in canonical["LINA"]
        ]
        assert all("effect_omitted" not in receipt for receipt in receipts)
        assert turn.action_outcomes == canonical
