"""Only current public applied receipts support declared durable prose changes."""

import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.engine import turn_controls
from backend.engine.chpm import inference, rendering, runtime
from backend.engine.chpm.errors import StaleControlError
from backend.engine.npc_actions import execution_frame
from backend.engine.npc_actions.contracts import Adjust, Give, Take
from backend.engine.npc_actions.publication import publish
from tests.conftest import TestSessionLocal
from tests.test_npc_execution_frame import prepared

TEXT = 'Lina: "I will examine it."\nLina takes the key.'


async def published(db, *, empty=False, requests=None):
    manager, observed, draft, turn = await prepared(db)
    proposed = [] if empty else (requests or [Take(tool="take_item", item_id="KEY")])
    for request in proposed:
        assert draft.execute(request)["status"] == "staged"
    draft.approved = True
    turn.action_outcomes = {"LINA": await publish(manager, draft)}
    turn.control = turn_controls.scope(manager, "narration_review", observation=observed)
    turn.initial.settings.max_input_chars = 64000
    turn.initial.settings.mode = "live"
    turn.present_names = {"LINA": "Lina", "SECOND": "Second observer"}
    await execution_frame.capture(manager, turn, observed)
    return manager, turn


def claim(turn, index=0):
    row = runtime.contract_data(turn)["LINA"]["authoritative_command_outcomes"][index]
    return {
        "actor_id": "LINA",
        "passage_id": "p1",
        "operation_id": row["operation_id"],
        "tool": row["tool"],
        "target_id": row["effect"].get("item_id", "LINA"),
    }


def reviewer(monkeypatch, changes):
    seen = []

    async def reply(_system, payload, _model, **_kwargs):
        body = json.loads(payload)
        seen.append(body)
        result = {
            "review_scope": body["review_scope"],
            "matches": True,
            "evidence": [{"actor_id": "LINA", "passage_id": "p0"}],
            "actions": [{"actor_id": "LINA", "passage_id": "p1"}],
        }
        if changes != "missing":
            result["completed_changes"] = changes
        return json.dumps(result)

    model = SimpleNamespace(
        model="mock",
        max_tokens=8192,
        request_timeout=10,
        aexecute_simple_task=AsyncMock(side_effect=reply),
    )
    monkeypatch.setattr(inference, "model_for", lambda *_args: model)
    return seen


async def test_actual_review_accepts_only_matching_current_public_receipt(monkeypatch):
    async with TestSessionLocal() as db:
        manager, turn = await published(db)
        before = deepcopy(manager.state.entity_states)
        seen = reviewer(monkeypatch, [claim(turn)])
        verdict = await rendering._review(manager, turn, TEXT, "")
        assert verdict.matches
        assert seen[0]["completed_changes_required"] is True
        assert turn.usage.calls == 1
        assert manager.state.entity_states == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("operation_id", "old-operation"),
        ("tool", "give_item"),
        ("target_id", "COAT"),
        ("actor_id", "SECOND"),
        ("passage_id", "p999"),
        ("recipient_id", "SECOND"),
    ],
)
async def test_mismatched_claim_is_negative_with_actionable_current_feedback(
    monkeypatch, field, value
):
    async with TestSessionLocal() as db:
        manager, turn = await published(db)
        proposed = {**claim(turn), field: value}
        reviewer(monkeypatch, [proposed])
        verdict = await rendering._review(manager, turn, TEXT, "")
        assert verdict.matches is False
        feedback = turn.review_change_feedback
        assert feedback["review_scope"]
        assert feedback["rejections"][0]["reason_code"]
        assert turn.usage.calls == 1 and not turn.usage.repairs


@pytest.mark.parametrize("changes", ["missing", None])
async def test_positive_coverage_absence_is_a_repairable_negative_not_success(monkeypatch, changes):
    async with TestSessionLocal() as db:
        manager, turn = await published(db, empty=True)
        reviewer(monkeypatch, changes)
        verdict = await rendering._review(manager, turn, TEXT, "")
        assert verdict.matches is False
        assert turn.review_change_feedback["rejections"][0]["reason_code"] == "coverage_required"


async def test_empty_plan_cannot_support_a_declared_mechanical_change(monkeypatch):
    async with TestSessionLocal() as db:
        manager, turn = await published(db, empty=True)
        reviewer(
            monkeypatch,
            [
                {
                    "actor_id": "LINA",
                    "passage_id": "p1",
                    "operation_id": "unissued",
                    "tool": "take_item",
                    "target_id": "KEY",
                }
            ],
        )
        verdict = await rendering._review(manager, turn, TEXT, "")
        assert not verdict.matches
        assert turn.action_outcomes == {"LINA": []}


async def test_unavailable_public_effect_cannot_be_reconstructed_from_host_receipt(monkeypatch):
    async with TestSessionLocal() as db:
        manager, turn = await published(db)
        proposed = claim(turn)
        turn.execution_frame = None
        reviewer(monkeypatch, [proposed])
        assert not (await rendering._review(manager, turn, TEXT, "")).matches
        assert turn.review_change_feedback["rejections"][0]["reason_code"] == "effect_unavailable"


async def test_stale_attempt_still_fails_before_claims_can_authorize_anything(monkeypatch):
    async with TestSessionLocal() as db:
        manager, turn = await published(db)
        reviewer(monkeypatch, [claim(turn)])
        turn_controls.begin(manager)
        with pytest.raises(StaleControlError):
            await rendering._review(manager, turn, TEXT, "")


async def test_malformed_completion_metadata_is_repairable_without_weakening_outer_scope(
    monkeypatch,
):
    async with TestSessionLocal() as db:
        manager, turn = await published(db)
        reviewer(monkeypatch, [{"actor_id": "LINA"}])
        verdict = await rendering._review(manager, turn, TEXT, "")
        assert not verdict.matches
        assert turn.review_change_feedback["rejections"] == [{"reason_code": "claims_invalid"}]


@pytest.mark.parametrize("policy", ["strict", "continue"])
async def test_bad_claim_uses_the_existing_one_prose_repair_and_rechecks(monkeypatch, policy):
    from backend.engine.chpm.state import KEY, load
    from tests.test_chpm_host_turn import run
    from tests.test_chpm_notebook_turn import ACTION, install
    from tests.test_chpm_observable_turn import prepare
    from tests.test_npc_action_execution_policy import ExecutionRoles

    class ClaimRoles(ExecutionRoles):
        async def simple(self, system, payload, model, **kwargs):
            result = await super().simple(system, payload, model, **kwargs)
            if kwargs.get("phase") == "validation":
                body = json.loads(result)
                body["completed_changes"] = []
                if len(self.reviews) == 1:
                    supplied = json.loads(payload)
                    body["completed_changes"] = [
                        {
                            "actor_id": "LINA",
                            "passage_id": next(iter(supplied["passages"])),
                            "operation_id": "unissued-operation",
                            "tool": "take_item",
                            "target_id": "KEY",
                        }
                    ]
                return json.dumps(body)
            return result

    roles = ClaimRoles()
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await prepare(db, "integrated", "json", False)
        kernel = load(state)
        kernel.settings.action_tools = True
        kernel.settings.failure_policy = policy
        state.entity_states = {**state.entity_states, KEY: kernel.model_dump()}
        await db.commit()
        manager, events = await run(db, user, ACTION)
        assert any(event.startswith("event: final") for event in events), "".join(events)
        assert len(roles.reviews) == 2 and len(roles.repairs) == 1
        feedback = roles.repairs[0][1]["completed_change_rejections"]
        assert feedback["rejections"][0]["reason_code"] == "operation_unavailable"
        assert load(manager.state).usage.calls == 6
        assert not load(manager.state).recovery.pending_gap_turns
        assert "unissued-operation" not in "".join(
            event for event in events if event.startswith("event: chunk")
        )


@pytest.mark.parametrize("regions,expected", [(["arms", "torso"], True), ([], False)])
async def test_actual_wardrobe_result_uses_region_sets_not_prose_or_array_order(
    monkeypatch, regions, expected
):
    async with TestSessionLocal() as db:
        manager, turn = await published(
            db,
            requests=[
                Adjust(tool="adjust_clothing", item_id="COAT", uncovered_regions=["torso", "arms"])
            ],
        )
        proposed = {**claim(turn), "uncovered_regions": regions}
        reviewer(monkeypatch, [proposed])
        verdict = await rendering._review(manager, turn, TEXT, "")
        assert verdict.matches is expected


@pytest.mark.parametrize("recipient,expected", [("SECOND", True), ("__player__", False)])
async def test_actual_chained_give_binds_the_specific_recipient(monkeypatch, recipient, expected):
    async with TestSessionLocal() as db:
        manager, turn = await published(
            db,
            requests=[
                Take(tool="take_item", item_id="KEY"),
                Give(tool="give_item", item_id="KEY", recipient_id="SECOND"),
            ],
        )
        proposed = {**claim(turn, 1), "recipient_id": recipient}
        reviewer(monkeypatch, [proposed])
        verdict = await rendering._review(manager, turn, TEXT, "")
        assert verdict.matches is expected


@pytest.mark.parametrize("protocol", ["json", "native"])
async def test_wear_and_removal_accept_empty_regions_copied_from_public_receipt(
    monkeypatch, protocol
):
    from backend.engine.npc_actions.contracts import TakeOff, Wear

    async with TestSessionLocal() as db:
        manager, turn = await published(
            db,
            requests=[
                TakeOff(tool="take_off_item", item_id="COAT"),
                Wear(tool="wear_item", item_id="COAT"),
            ],
        )
        turn.initial.settings.tool_protocol = protocol
        for i, line in enumerate(["Lina takes off the coat.", "Lina puts the coat on."]):
            proposed = claim(turn, i)
            receipt = turn.action_outcomes["LINA"][i]
            assert receipt["effect"]["uncovered_regions"] == []
            for value in (None, []):
                reviewer(monkeypatch, [{**proposed, "uncovered_regions": value}])
                verdict = await rendering._review(
                    manager, turn, 'Lina: "I will examine it."\n' + line, ""
                )
                assert verdict.matches, turn.review_change_feedback


@pytest.mark.parametrize(
    "tool,actual,claimed,hidden,reason",
    [
        ("take_off_item", [], ["arms"], False, "result_mismatch"),
        ("wear_item", ["arms"], [], False, "result_mismatch"),
        ("wear_item", None, [], False, "result_mismatch"),
        ("wear_item", [], [], True, "effect_unavailable"),
        ("take_item", [], [], False, "result_mismatch"),
        ("adjust_clothing", [], None, False, "result_mismatch"),
        ("adjust_clothing", [], [], False, ""),
    ],
)
def test_empty_wardrobe_regions_never_authorize_another_attribute(
    tool, actual, claimed, hidden, reason
):
    from backend.engine.chpm import passages, receipt_review

    review_claim = passages.CompletedChange(
        actor_id="LINA",
        passage_id="p1",
        operation_id="op1",
        tool=tool,
        target_id="COAT",
        uncovered_regions=claimed,
    )
    row = {
        "tool": tool,
        "effect": {"item_id": "COAT", "uncovered_regions": actual},
        "effect_omitted": hidden,
    }
    assert receipt_review._effect_reason(review_claim, row) == reason


@pytest.mark.parametrize("coarse", [False, True])
async def test_partial_placement_claim_must_match_the_published_adjustment(monkeypatch, coarse):
    async with TestSessionLocal() as db:
        manager, turn = await published(
            db,
            requests=[
                Adjust(
                    tool="adjust_clothing",
                    item_id="COAT",
                    uncovered_regions=[],
                    partially_removed=coarse,
                )
            ],
        )
        receipt = turn.action_outcomes["LINA"][0]["effect"]
        assert receipt["uncovered_regions"] == (["arms"] if coarse else [])
        proposed = {**claim(turn), "uncovered_regions": receipt["uncovered_regions"]}
        for marker in (None, False, True):
            reviewer(monkeypatch, [{**proposed, "partially_removed": marker}])
            verdict = await rendering._review(
                manager, turn, 'Lina: "My coat."\nLina adjusts the coat.', ""
            )
            assert verdict.matches is (bool(marker) == coarse), turn.review_change_feedback
