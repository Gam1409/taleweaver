"""A completed transfer can disagree with one accepted, occurrence-bound public receipt."""

from copy import deepcopy

import pytest

from backend.core.text_passages import index, spans
from backend.engine.chpm import passages, rendering
from backend.engine.narrated_items.schema import ItemAction
from backend.engine.npc_actions import custody_citations as custody
from backend.engine.npc_actions.contracts import Give, PutDown, Take
from backend.engine.visual_novel.continuity import SCENE
from tests.conftest import TestSessionLocal
from tests.test_npc_completed_change_review import claim, published

TEXT = "A visitor waits. The brass cup changes hands. The brass cup changes hands."
RESOLUTION = "The current command results are final."


def review(turn, text, *claims):
    return passages.ReceiptReview(
        review_scope=rendering._review_scope(turn, index(text), RESOLUTION),
        matches=True,
        completed_changes=list(claims),
    )


def action(text=TEXT, *, passage="p1", source="LINA", destination=SCENE, **fields):
    span = spans(text)[passage]
    return ItemAction.model_validate(
        {
            "item_id": "KEY",
            "source_owner": source,
            "destination_owner": destination,
            "disposition": "held",
            "basis": "completed",
            "evidence": span.text,
            "evidence_span": {"start": span.start, "end": span.end},
            **fields,
        }
    )


async def test_reviewed_pickup_vs_completed_return_to_scene_never_writes():
    async with TestSessionLocal() as db:
        manager, turn = await published(db)
        before = deepcopy(manager.state.entity_states)
        row = claim(turn)
        proof = custody.capture(turn, review(turn, TEXT, row), TEXT, RESOLUTION)
        failures = custody.conflicts(proof, turn, TEXT, RESOLUTION, [action()])
        assert len(failures) == 1
        failure = failures[0]
        assert failure["reason_code"] == "custody_direction_mismatch"
        assert failure["operation_id"] == row["operation_id"] and failure["passage_id"] == "p1"
        assert failure["expected_public_result"] == {
            "tool": "take_item",
            "target_id": "KEY",
            "source_owner": SCENE,
            "destination_owner": "LINA",
        }
        assert manager.state.entity_states == before
        for other in (
            action(source=SCENE, destination="LINA"),
            action(source=SCENE, destination="SECOND"),
            action(source="LINA", destination="LINA"),
            action(source="LINA", destination="SECOND"),
            action(item_id="COAT"),
            action(passage="p2"),
            action(basis="hypothetical"),
            action(evidence_span=None),
            action(evidence="The brass cup", evidence_span={"start": 17, "end": 30}),
            action(evidence=TEXT, evidence_span={"start": 0, "end": len(TEXT)}),
        ):
            assert custody.conflicts(proof, turn, TEXT, RESOLUTION, [other]) == []


async def test_only_same_passage_multiple_citations_may_explain_direction():
    async with TestSessionLocal() as db:
        _, turn = await published(
            db,
            requests=[
                Take(tool="take_item", item_id="KEY"),
                PutDown(tool="put_down_item", item_id="KEY"),
            ],
        )
        take = claim(turn, 0)
        drop = claim(turn, 1)
        same = custody.capture(turn, review(turn, TEXT, take, drop), TEXT, RESOLUTION)
        assert custody.conflicts(same, turn, TEXT, RESOLUTION, [action()]) == []
        partial = custody.capture(turn, review(turn, TEXT, take), TEXT, RESOLUTION)
        assert custody.conflicts(partial, turn, TEXT, RESOLUTION, [action()]) == []
        split = custody.capture(
            turn, review(turn, TEXT, take, {**drop, "passage_id": "p2"}), TEXT, RESOLUTION
        )
        assert [
            row["operation_id"]
            for row in custody.conflicts(split, turn, TEXT, RESOLUTION, [action()])
        ] == [take["operation_id"]]
        assert custody.conflicts(split, turn, TEXT, RESOLUTION, [action(passage="p2")]) == []


async def test_wrong_recipient_only_for_unambiguous_cited_source():
    async with TestSessionLocal() as db:
        _, turn = await published(
            db,
            requests=[
                Take(tool="take_item", item_id="KEY"),
                Give(tool="give_item", item_id="KEY", recipient_id="SECOND"),
            ],
        )
        receipt = {**claim(turn, 1), "recipient_id": "SECOND"}
        proof = custody.capture(turn, review(turn, TEXT, receipt), TEXT, RESOLUTION)
        issues = custody.conflicts(
            proof, turn, TEXT, RESOLUTION, [action(destination="__player__")]
        )
        assert issues[0]["expected_public_result"]["destination_owner"] == "SECOND"
        assert (
            custody.conflicts(
                proof, turn, TEXT, RESOLUTION, [action(source="SECOND", destination="__player__")]
            )
            == []
        )


async def test_freshness_omitted_data_and_rejected_review_cannot_authorize_contradiction():
    async with TestSessionLocal() as db:
        _, turn = await published(db)
        raw = review(turn, TEXT, claim(turn))
        proof = custody.capture(turn, raw, TEXT, RESOLUTION)
        assert proof is not None
        assert custody.conflicts(proof, turn, TEXT, "changed", [action()]) == []
        assert custody.conflicts(proof, turn, TEXT + " ", RESOLUTION, [action()]) == []
        assert (
            custody.capture(turn, raw.model_copy(update={"matches": False}), TEXT, RESOLUTION)
            is None
        )
        assert (
            custody.capture(
                turn, raw.model_copy(update={"review_scope": "stale"}), TEXT, RESOLUTION
            )
            is None
        )
        assert (
            custody.capture(
                turn, review(turn, TEXT, {**claim(turn), "target_id": "COAT"}), TEXT, RESOLUTION
            )
            is None
        )
        turn.action_drafts["LINA"].published_results = []
        assert custody.conflicts(proof, turn, TEXT, RESOLUTION, [action()]) == []
        assert custody.capture(turn, raw, TEXT, RESOLUTION) is None


async def test_retry_matches_unique_unchanged_passage_on_new_review_without_borrowing_ids():
    old = "Someone waits. The object changes hands."
    new = "The room is quiet. Someone waits. The object changes hands."
    async with TestSessionLocal() as db:
        _, turn = await published(db)
        proof = custody.capture(turn, review(turn, old, claim(turn)), old, RESOLUTION)
        initial = custody.conflicts(proof, turn, old, RESOLUTION, [action(old)])
        assert len(initial) == 1
        turn.review_operation = {}
        second = review(turn, new)
        assert second.review_scope != proof.review_scope
        assert custody.capture(turn, second, new, RESOLUTION) is None
        fresh = action(new, passage="p2")
        failures = custody.repeated_conflicts(proof, initial, turn, new, [fresh])
        assert failures == [{**initial[0], "passage_id": "p2"}]
        for other in (
            action(new, passage="p1"),
            action(new, passage="p2", source=SCENE, destination="LINA"),
            action(new, passage="p2", basis="attempt"),
        ):
            assert custody.repeated_conflicts(proof, initial, turn, new, [other]) == []
        assert (
            custody.repeated_conflicts(
                proof, initial, turn, new, [fresh, action(new, passage="p2", destination="SECOND")]
            )
            == []
        )
        repeated = new + " The object changes hands."
        assert (
            custody.repeated_conflicts(
                proof, initial, turn, repeated, [action(repeated, passage="p2")]
            )
            == []
        )
        rewritten = new.replace("object changes hands", "cup changes hands")
        assert (
            custody.repeated_conflicts(
                proof, initial, turn, rewritten, [action(rewritten, passage="p2")]
            )
            == []
        )
        turn.action_drafts["LINA"].approved = False
        assert custody.repeated_conflicts(proof, initial, turn, new, [fresh]) == []


async def test_duplicate_original_passages_cannot_rebind_across_repair():
    async with TestSessionLocal() as db:
        _, turn = await published(db)
        proof = custody.capture(turn, review(turn, TEXT, claim(turn)), TEXT, RESOLUTION)
        initial = custody.conflicts(proof, turn, TEXT, RESOLUTION, [action()])
        changed = "A visitor waits. The brass cup changes hands."
        assert custody.repeated_conflicts(proof, initial, turn, changed, [action(changed)]) == []


async def test_a_second_real_transfer_cannot_be_disproved_on_a_repair_without_citations():
    text = "A visitor waits. The brass cup moves. Then it rests."
    async with TestSessionLocal() as db:
        _, turn = await published(
            db,
            requests=[
                Take(tool="take_item", item_id="KEY"),
                PutDown(tool="put_down_item", item_id="KEY"),
            ],
        )
        proof = custody.capture(
            turn,
            review(turn, text, claim(turn), {**claim(turn, 1), "passage_id": "p2"}),
            text,
            RESOLUTION,
        )
        initial = custody.conflicts(proof, turn, text, RESOLUTION, [action(text)])
        assert (
            initial and custody.repeated_conflicts(proof, initial, turn, text, [action(text)]) == []
        )


@pytest.mark.parametrize(
    "fault", ["private", "missing_direction", "malformed_direction", "foreign_attempt"]
)
async def test_missing_unpublished_or_invalid_fields_do_not_enter_repair(fault):
    async with TestSessionLocal() as db:
        _, turn = await published(db)
        proposed = claim(turn)
        if fault == "private":
            turn.execution_frame.entities.pop("KEY")
        elif fault == "foreign_attempt":
            turn.control = {**turn.control, "attempt_id": "another-attempt"}
            raw = passages.ReceiptReview(
                review_scope="old", matches=True, completed_changes=[proposed]
            )
            assert custody.capture(turn, raw, TEXT, RESOLUTION) is None
            return
        else:
            for row in (
                turn.action_outcomes["LINA"][0],
                turn.action_drafts["LINA"].published_results[0],
            ):
                row["effect"]["source_owner"] = [] if fault == "malformed_direction" else None
        assert custody.capture(turn, review(turn, TEXT, proposed), TEXT, RESOLUTION) is None


async def test_current_publication_includes_actor_visibility_and_review_has_no_write_authority():
    async with TestSessionLocal() as db:
        _, turn = await published(db)
        proof = custody.capture(turn, review(turn, TEXT, claim(turn)), TEXT, RESOLUTION)
        assert custody.is_current(proof, turn)
        assert (
            custody.conflicts(
                proof, turn, TEXT, RESOLUTION, [action(source="SECOND", destination="LINA")]
            )
            == []
        )
        assert (
            custody.conflicts(proof, turn, TEXT, RESOLUTION, [action(destination="HIDDEN_NPC")])
            == []
        )
        del turn.execution_frame.entities["SECOND"]
        assert not custody.is_current(proof, turn)
