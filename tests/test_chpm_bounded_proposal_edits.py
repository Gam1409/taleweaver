"""A tight repair edits the original proposal without rebuilding its valid fields."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.engine.chpm import choice_grounds, inference, proposal_attempt
from backend.engine.chpm.errors import RecoverableChpmError
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.proposal_draft import Draft
from backend.engine.chpm.schema import Settings, Usage
from tests.chpm_repair_fixture import corrections
from tests.test_chpm_kernel import wire_proposal
from tests.test_chpm_proposal_repair_context import accept_choice
from tests.test_chpm_reliability import Replies


def tight_request(original):
    context = {"pinned_context": "Current exact observation and identity. " * 120}
    system, content = inference.compose("Use the schema.", context, Draft, {})
    allowance = len(system) + len(content) + 1100
    return context, Settings(mode="live", actor_ids=["npc"], max_input_chars=allowance)


async def test_budget_limited_repair_uses_edits_and_preserves_unedited_fields():
    original = wire_proposal()
    original["choice"]["reason"] = "x" * 301
    saved = deepcopy(original)
    edits = {"edits": [{"op": "replace", "path": "/choice/reason", "value": "Keep the purpose."}]}
    model = Replies([json.dumps(original), json.dumps(edits)])
    manager = SimpleNamespace(_chpm_model_factory=lambda _role: model, game_id="fixture")
    context, settings = tight_request(original)
    usage = Usage()

    decision = await proposal_attempt.request(
        manager, settings, usage, "Use the schema.", context, Draft, {}, accept_choice
    )

    assert decision.choice_preference.reason == "Keep the purpose."
    feedback = model.requests[1][2]["proposal_feedback"]
    assert feedback["repair_mode"] == "field_edits"
    assert feedback["rejected_proposal"] == original == saved
    assert model.requests[1][2]["pinned_context"] == context["pinned_context"]
    assert usage.calls == 2 and usage.proposal_repairs == 1
    assert [row[0] for row in model.requests] == ["proposal", "proposal_repair"]


async def test_edited_proposal_still_passes_the_original_semantic_validation():
    original = wire_proposal()
    original["choice"].update(reason="x" * 301, motive_ids=["invented"])
    edits = {"edits": [{"op": "replace", "path": "/choice/reason", "value": "A short reason."}]}
    model = Replies([json.dumps(original), json.dumps(edits)])
    manager = SimpleNamespace(_chpm_model_factory=lambda _role: model, game_id="fixture")
    context, settings = tight_request(original)
    usage = Usage()

    with pytest.raises(RecoverableChpmError, match="remains invalid"):
        await proposal_attempt.request(
            manager, settings, usage, "Use the schema.", context, Draft, {}, accept_choice
        )

    assert model.requests[1][2]["proposal_feedback"]["repair_mode"] == "field_edits"
    assert usage.calls == 2 and usage.proposal_repairs == 1


def test_missing_clarification_gate_is_reported_before_other_errors_are_repaired():
    original = wire_proposal()
    original["candidates"]["CLARIFY"] = deepcopy(original["candidates"]["CONTINUE"])
    original["choice"]["preferred"] = "CLARIFY"
    hint = choice_grounds.repair_hint(original)
    assert "question_gate" in hint
    assert "CLARIFY" in hint
    assert original["choice"]["preferred"] == "CLARIFY"


async def test_source_error_repair_also_receives_the_independent_missing_gate_diagnostic():
    original = wire_proposal()
    original["candidates"]["CLARIFY"] = deepcopy(original["candidates"]["CONTINUE"])
    original["choice"]["preferred"] = "CLARIFY"
    corrected = deepcopy(original)
    corrected["choice"]["preferred"] = "CONTINUE"
    model = Replies([json.dumps(original), corrections(("/choice/preferred", "CONTINUE"))])
    manager = SimpleNamespace(_chpm_model_factory=lambda _role: model, game_id="fixture")
    usage = Usage()

    def accept(draft):
        if draft.choice.preferred == "CLARIFY":
            raise ChpmError("An experience needs a current observed trigger.")
        return accept_choice(draft)

    await proposal_attempt.request(
        manager,
        Settings(mode="live", actor_ids=["npc"]),
        usage,
        "Use the schema.",
        {},
        Draft,
        {},
        accept,
    )

    feedback = model.requests[1][2]["proposal_feedback"]["error"]
    assert "current observed trigger" in feedback
    assert "question_gate" in feedback
    assert usage.calls == 2
