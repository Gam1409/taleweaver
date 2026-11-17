"""A changed kind needs useful bounded feedback; the model still chooses the correction."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.engine.chpm import (
    appraisal_context,
    choice_grounds,
    motivation,
    proposal_attempt,
    quote_references,
    semantic_choice,
)
from backend.engine.chpm.proposal_draft import Draft
from backend.engine.chpm.proposal_references import ReferenceDraft
from backend.engine.chpm.schema import Settings, Usage
from tests.chpm_reference_fixture import proposal as reference_proposal
from tests.chpm_repair_fixture import corrections
from tests.test_chpm_appraisal import heard
from tests.test_chpm_kernel import observation, wire_proposal
from tests.test_chpm_reliability import Replies
from tests.test_chpm_semantic_choice import prior


def retained():
    previous = prior()
    previous.selected.kind = "ACCEPT"
    return previous


@pytest.mark.parametrize("schema", [Draft, ReferenceDraft])
@pytest.mark.parametrize("correction", ["maintain", "revise"])
async def test_changed_kind_feedback_keeps_both_legal_model_selected_corrections(
    schema, correction
):
    value = heard(message="input", text="The inspection is complete. Please review the report.")
    window = appraisal_context.build(value, current_message_id="input")
    catalogue = motivation.build(value, [], window)
    references = quote_references.build(window, catalogue, {})
    previous = retained()
    payload = {"previous_intention": previous.model_dump(), "appraisal_context": window.payload}
    original = wire_proposal()
    original["candidates"]["ACCEPT"] = deepcopy(original["candidates"]["CONTINUE"])
    current_basis = [item.model_dump() for item in references.quotes.values()][:2]
    original["choice"].update(
        preferred="CONTINUE",
        continuity="maintain",
        change_basis=current_basis,
    )
    identifiers = {**window.identifiers(), **catalogue.identifiers()}
    if schema is ReferenceDraft:
        payload = references.project(payload)
        original = reference_proposal(original, payload)
        identifiers = {key: list(values) for key, values in references.identifiers.items()}
    before = deepcopy(original)
    changes = (
        (("/choice/preferred", "ACCEPT"), ("/choice/change_basis", []))
        if correction == "maintain"
        else (("/choice/continuity", "revise"),)
    )
    model = Replies([json.dumps(original), corrections(*changes)])
    manager = SimpleNamespace(game_id="session", _chpm_model_factory=lambda _role: model)
    usage = Usage()

    def accept(draft):
        raw = (
            draft.materialize(catalogue, references, [])
            if isinstance(draft, ReferenceDraft)
            else draft.materialize(catalogue)
        )
        return semantic_choice.select(
            "npc",
            observation(),
            raw.canonical(),
            raw.question_gate,
            raw.choice,
            motivation.resolve(raw, catalogue),
            window,
            previous,
            context_hash="context",
        )

    with pytest.raises(ValueError, match="same kind"):
        accept(schema.model_validate(original))
    decision = await proposal_attempt.request(
        manager,
        Settings(mode="live", actor_ids=["npc"]),
        usage,
        "Use the schema.",
        payload,
        schema,
        identifiers,
        accept,
    )

    feedback = model.requests[1][2]["proposal_feedback"]["error"]
    assert "Retained kind is ACCEPT" in feedback
    assert "preferred CONTINUE cannot maintain" in feedback
    assert "keep ACCEPT" in feedback
    assert "continuity='maintain'" in feedback and "change_basis=[]" in feedback
    assert "continuity='revise'" in feedback and "exact offered change_basis" in feedback
    assert len(feedback) <= 600
    assert decision.choice_preference.continuity == correction
    assert decision.selected.kind == ("ACCEPT" if correction == "maintain" else "CONTINUE")
    assert bool(decision.choice_preference.change_basis) == (correction == "revise")
    assert original == before and previous.selected.kind == "ACCEPT"
    assert usage.calls == len(model.requests) == 2 and usage.proposal_repairs == 1


@pytest.mark.parametrize("basis", [[], [{"source_id": "e1", "quote": "A current report."}]])
def test_kind_conflict_is_diagnosed_even_after_the_basis_only_partial_correction(basis):
    raw = wire_proposal()
    raw["choice"].update(continuity="maintain", change_basis=basis)

    hint = choice_grounds.repair_hint(raw, previous_intention=retained().model_dump())
    assert "Retained kind is ACCEPT" in hint and "preferred CONTINUE cannot maintain" in hint
    assert "keep ACCEPT" in hint and "continuity='revise'" in hint
    assert "continuity='new'" not in hint


@pytest.mark.parametrize(
    "previous",
    [None, {}, {"selected": None}, {"selected": {}}, {"selected": {"kind": "unknown"}}, []],
)
def test_missing_or_legacy_previous_details_keep_the_existing_generic_hint(previous):
    raw = wire_proposal()
    raw["choice"].update(
        continuity="maintain", change_basis=[{"source_id": "e1", "quote": "A current report."}]
    )

    legacy = choice_grounds.repair_hint(raw)

    assert "choice.change_basis=[]" in legacy
    assert choice_grounds.repair_hint(raw, previous_intention=previous) == legacy
    assert "Retained kind" not in legacy


def test_explicit_no_previous_intention_preserves_the_new_intention_guidance():
    raw = wire_proposal()
    raw["choice"]["continuity"] = "maintain"

    hint = choice_grounds.repair_hint(raw, no_previous_intention=True, previous_intention=None)

    assert "previous_intention is null" in hint and "choice.continuity='new'" in hint
    assert "Retained kind" not in hint


@pytest.mark.parametrize("kind", ["CONTINUE", "INITIATE"])
def test_allowed_maintain_transitions_get_no_kind_change_hint(kind):
    raw = wire_proposal()
    raw["choice"].update(continuity="maintain", change_basis=[])
    previous = retained().model_dump()
    previous["selected"]["kind"] = kind

    assert choice_grounds.repair_hint(raw, previous_intention=previous) == ""


def test_a_grounded_revision_is_not_told_to_keep_the_previous_kind():
    raw = wire_proposal()
    raw["choice"].update(
        continuity="revise", change_basis=[{"source_id": "e1", "quote": "A current report."}]
    )

    assert choice_grounds.repair_hint(raw, previous_intention=retained().model_dump()) == ""
