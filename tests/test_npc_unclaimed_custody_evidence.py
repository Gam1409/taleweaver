"""Every occurrence is checked against its own public operation and per-item chronology."""

import json
from typing import get_args

import pytest

from backend.engine.clothing.body_schema import BodySlot
from backend.engine.npc_actions import custody_check
from backend.engine.npc_actions import custody_citations as custody
from backend.engine.npc_actions.contracts import Give, PutDown, Take, TakeOff
from backend.engine.visual_novel.continuity import SCENE
from tests.conftest import TestSessionLocal
from tests.test_npc_completed_change_review import claim, published
from tests.test_npc_custody_citations import RESOLUTION, action, review


@pytest.mark.parametrize("other_item", [False, True])
async def test_a_valid_citation_elsewhere_does_not_hide_an_uncited_reverse_transfer(other_item):
    text = "The first action completes. The key returns to the room."
    requests = [Take(tool="take_item", item_id="KEY")]
    if other_item:
        requests += [
            TakeOff(tool="take_off_item", item_id="COAT"),
            PutDown(tool="put_down_item", item_id="COAT"),
        ]
    async with TestSessionLocal() as db:
        _, turn = await published(db, requests=requests)
        cited = {**claim(turn, len(requests) - 1), "passage_id": "p0"}
        proof = custody.capture(turn, review(turn, text, cited), text, RESOLUTION)

        issues = custody.conflicts(proof, turn, text, RESOLUTION, [action(text, passage="p1")])

        assert len(issues) == 1 and issues[0]["reason_code"] == "custody_direction_mismatch"
        assert issues[0]["expected_public_result"]["target_id"] == "KEY"
        assert issues[0]["passage_id"] == "p1"


@pytest.mark.parametrize("cited", [False, True])
async def test_confirmed_steps_cannot_be_reversed_between_distinct_passages(cited):
    text = "The key is put down. The key is picked up."
    async with TestSessionLocal() as db:
        _, turn = await published(
            db,
            requests=[
                Take(tool="take_item", item_id="KEY"),
                PutDown(tool="put_down_item", item_id="KEY"),
            ],
        )
        claims = (
            [{**claim(turn, 1), "passage_id": "p0"}, {**claim(turn, 0), "passage_id": "p1"}]
            if cited
            else []
        )
        proof = custody.capture(turn, review(turn, text, *claims), text, RESOLUTION)
        changes = [
            action(text, passage="p0"),
            action(text, passage="p1", source=SCENE, destination="LINA"),
        ]

        issues = custody.conflicts(proof, turn, text, RESOLUTION, changes)

        assert len(issues) == 1
        assert issues[0]["reason_code"] == "custody_operation_order_mismatch"


@pytest.mark.parametrize("cited", [False, True])
async def test_one_applied_operation_cannot_explain_two_independent_completion_occurrences(cited):
    text = "The key is picked up. The key is picked up again."
    async with TestSessionLocal() as db:
        _, turn = await published(db)
        claims = [{**claim(turn), "passage_id": "p0"}] if cited else []
        proof = custody.capture(turn, review(turn, text, *claims), text, RESOLUTION)
        changes = [
            action(text, passage=key, source=SCENE, destination="LINA") for key in ("p0", "p1")
        ]

        issues = custody.conflicts(proof, turn, text, RESOLUTION, changes)

        assert len(issues) == 1 and issues[0]["reason_code"] == "custody_operation_reused"
        assert issues[0]["passage_id"] == "p1"


async def test_an_independent_third_party_can_pass_on_a_lawfully_received_item():
    text = "The second observer hands the key to the player."
    async with TestSessionLocal() as db:
        _, turn = await published(
            db,
            requests=[
                Take(tool="take_item", item_id="KEY"),
                Give(tool="give_item", item_id="KEY", recipient_id="SECOND"),
            ],
        )
        proof = custody.capture(turn, review(turn, text), text, RESOLUTION)
        changes = [action(text, passage="p0", source="SECOND", destination="__player__")]

        assert custody.conflicts(proof, turn, text, RESOLUTION, changes) == []


@pytest.mark.parametrize(
    "placement", [{"uncovered_regions": ["arms"]}, {"attachment_slot": get_args(BodySlot)[0]}]
)
async def test_extractor_placement_details_never_become_public_repair_authority(placement):
    text = "The key moves onto the actor."
    async with TestSessionLocal() as db:
        _, turn = await published(db)
        proof = custody.capture(turn, review(turn, text), text, RESOLUTION)
        changes = [
            action(
                text,
                passage="p0",
                source=SCENE,
                destination="LINA",
                disposition="worn",
                **placement,
            )
        ]

        issues = custody.conflicts(proof, turn, text, RESOLUTION, changes)

        assert len(issues) == 1 and issues[0]["reason_code"] == "custody_placement_mismatch"
        encoded = json.dumps(issues)
        assert "attachment_slot" not in encoded and "uncovered_regions" not in encoded


@pytest.mark.parametrize("claimed", [False, True])
async def test_a_second_ambiguous_reading_does_not_confirm_the_same_unfixed_operation(claimed):
    original = "The key is lifted. The key changes hands."
    corrected = "The room is quiet. " + original
    async with TestSessionLocal() as db:
        _, turn = await published(db)
        claims = [{**claim(turn), "passage_id": "p0"}] if claimed else []
        proof = custody.capture(turn, review(turn, original, *claims), original, RESOLUTION)
        initial = custody.conflicts(proof, turn, original, RESOLUTION, [action(original)])
        assert len(initial) == 1
        turn.reviewed_custody = custody.capture(
            turn, review(turn, corrected), corrected, RESOLUTION
        )
        ambiguous = [
            action(corrected, passage="p2"),
            action(corrected, passage="p2", source=SCENE, destination="LINA"),
        ]
        assert (
            custody.conflicts(turn.reviewed_custody, turn, corrected, RESOLUTION, ambiguous) == []
        )

        with pytest.raises(custody_check.CustodyDisagreementError):
            custody_check.compare(
                turn, corrected, RESOLUTION, ambiguous, custody_check.Recheck(proof, initial)
            )


async def test_a_corrected_placement_can_return_to_the_confirmed_carried_result():
    original = "The key changes hands."
    corrected = "The room is quiet. " + original
    async with TestSessionLocal() as db:
        _, turn = await published(db)
        proof = custody.capture(turn, review(turn, original), original, RESOLUTION)
        initial = custody.conflicts(
            proof,
            turn,
            original,
            RESOLUTION,
            [action(original, passage="p0", source=SCENE, destination="LINA", disposition="worn")],
        )
        assert initial[0]["reason_code"] == "custody_placement_mismatch"

        assert (
            custody.repeated_conflicts(
                proof,
                initial,
                turn,
                corrected,
                [action(corrected, source=SCENE, destination="LINA", disposition="held")],
            )
            == []
        )


async def test_repair_uses_the_public_player_reference_for_a_wrong_transfer_recipient():
    text = "The key is handed to the player."
    async with TestSessionLocal() as db:
        _, turn = await published(
            db,
            requests=[
                Take(tool="take_item", item_id="KEY"),
                Give(tool="give_item", item_id="KEY", recipient_id="SECOND"),
            ],
        )
        raw = {**claim(turn, 1), "recipient_id": "SECOND", "passage_id": "p0"}
        proof = custody.capture(turn, review(turn, text, raw), text, RESOLUTION)

        issues = custody.conflicts(
            proof, turn, text, RESOLUTION, [action(text, passage="p0", destination="__player__")]
        )

        assert issues[0]["expected_public_result"]["destination_owner"] == "SECOND"
        assert issues[0]["reported_public_direction"]["destination_owner"] == "@player"
        assert "__player__" not in json.dumps(issues)
