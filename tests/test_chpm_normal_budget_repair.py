"""Normal-budget correction preserves the rejected draft's unedited cognitive fields."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.engine.chpm import (
    appraisal,
    appraisal_context,
    experience,
    inference,
    motivation,
    proposal_attempt,
    proposal_repair,
    semantic_choice,
)
from backend.engine.chpm.errors import RecoverableChpmError
from backend.engine.chpm.proposal_draft import Draft
from backend.engine.chpm.schema import Settings, Usage
from tests.test_chpm_appraisal import heard, proposal
from tests.test_chpm_kernel import observation, wire_proposal
from tests.test_chpm_proposal_repair_context import accept_choice
from tests.test_chpm_reliability import Replies
from tests.test_chpm_semantic_choice import prior


async def test_normal_budget_two_choice_edits_preserve_empty_experiences_and_cited_fields():
    mind = heard(message="input")
    window = appraisal_context.build(mind, current_message_id="input")
    catalogue = motivation.build(mind, [], window)
    original = wire_proposal()
    original["experiences"] = []
    original["new_beliefs"] = [proposal().model_dump(mode="json", exclude={"belief_id"})]
    original["choice"].update(
        reason="x" * 301,
        continuity="maintain",
        change_basis=[{"source_id": "e1", "quote": "missed my promise"}],
    )
    before = deepcopy(original)
    expected = deepcopy(original)
    expected["choice"].update(reason="Continue my established purpose.", change_basis=[])
    expected = Draft.model_validate(expected).model_dump(mode="json")
    corrected = {
        "edits": [
            {
                "op": "replace",
                "path": "/choice/reason",
                "value": "Continue my established purpose.",
            },
            {"op": "replace", "path": "/choice/change_basis", "value": []},
        ]
    }
    model = Replies([json.dumps(original), json.dumps(corrected)])
    manager = SimpleNamespace(_chpm_model_factory=lambda _role: model, game_id="fixture")
    usage = Usage()
    checked = []

    def accept(draft):
        checked.append(draft.model_dump(mode="json"))
        raw = draft.materialize(catalogue)
        changed, _ = appraisal.accept(mind, raw.interpretations, window, message_id="input")
        changed, _ = experience.accept(
            changed, raw.experiences, window, catalogue, message_id="input"
        )
        assert len(changed.snapshot.beliefs) == 1 and not changed.snapshot.experiences
        return semantic_choice.select(
            "npc",
            observation(),
            raw.canonical(),
            raw.question_gate,
            raw.choice,
            motivation.resolve(raw, catalogue),
            window,
            prior(),
            context_hash="same-context",
        )

    decision = await proposal_attempt.request(
        manager,
        Settings(mode="live", actor_ids=["npc"]),
        usage,
        "Use the schema.",
        {"appraisal_context": window.payload, "previous_intention": prior().model_dump()},
        Draft,
        {},
        accept,
    )

    assert checked == [expected]
    assert checked[0]["experiences"] == []
    assert checked[0]["new_beliefs"] == original["new_beliefs"]
    assert original == before
    assert decision.choice_preference.continuity == "maintain"
    assert decision.choice_preference.change_basis == []
    assert model.requests[1][2]["proposal_feedback"]["repair_mode"] == "field_edits"
    assert usage.calls == 2 and usage.proposal_repairs == 1


async def test_unparseable_draft_keeps_complete_object_repair_without_an_edit_base():
    original = '{"choice":'
    model = Replies([original, json.dumps(wire_proposal())])
    host = SimpleNamespace(_chpm_model_factory=lambda _role: model, game_id="fixture")
    usage = Usage()
    decision = await proposal_attempt.request(
        host,
        Settings(mode="live", actor_ids=["npc"]),
        usage,
        "Use the schema.",
        {},
        Draft,
        {},
        accept_choice,
    )
    feedback = model.requests[1][2]["proposal_feedback"]
    assert "rejected_proposal" not in feedback and "repair_mode" not in feedback
    assert decision.choice_preference.preferred == "CONTINUE"
    assert usage.calls == 2 and usage.proposal_repairs == 1


async def test_oversized_draft_keeps_bounded_full_repair_and_required_context():
    original = wire_proposal()
    original["choice"]["reason"] = "x" * 40000
    before = deepcopy(original)
    model = Replies([json.dumps(original), json.dumps(wire_proposal())])
    host = SimpleNamespace(_chpm_model_factory=lambda _role: model, game_id="fixture")
    usage, settings = Usage(), Settings(mode="live", actor_ids=["npc"])
    context = {"pinned_context": "Required exact current observation and identity."}
    await proposal_attempt.request(
        host,
        settings,
        usage,
        "Use the schema.",
        context,
        Draft,
        {},
        accept_choice,
    )
    _, prompt, payload = model.requests[1]
    feedback = payload["proposal_feedback"]
    assert "input budget" in feedback["rejected_proposal_omitted"]
    assert "rejected_proposal" not in feedback and "repair_mode" not in feedback
    assert payload["pinned_context"] == context["pinned_context"]
    assert (
        len(prompt) + len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        <= settings.max_input_chars
    )
    assert original == before
    assert usage.calls == 2 and usage.proposal_repairs == 1


def test_oversized_edit_path_catalogue_can_fall_back_to_a_fitting_complete_draft():
    candidate = wire_proposal()
    candidate.update({f"extra{index}" + "x" * 160: {"nested": "value"} for index in range(60)})
    context, instruction, feedback = (
        {"pinned_context": "Retain this."},
        "Use the schema.",
        "Extra fields.",
    )
    full = proposal_repair.payload_for(
        context,
        Draft,
        feedback,
        candidate,
        instruction=instruction,
        identifiers={},
        limit=192000,
    )
    prompt, content = inference.compose(instruction, full, Draft, {})
    limit = Settings(max_input_chars=len(prompt) + len(content)).max_input_chars
    prepared = proposal_repair.prepare(
        context,
        Draft,
        feedback,
        candidate,
        instruction=instruction,
        identifiers={},
        limit=limit,
    )
    assert prepared.original is None
    assert prepared.payload["proposal_feedback"]["rejected_proposal"] == candidate
    assert prepared.payload["pinned_context"] == context["pinned_context"]


async def test_a_full_object_returned_to_an_edit_round_cannot_spend_another_retry():
    original = wire_proposal()
    original["choice"]["reason"] = "x" * 301
    model = Replies([json.dumps(original), json.dumps(wire_proposal())])
    host = SimpleNamespace(_chpm_model_factory=lambda _role: model, game_id="fixture")
    usage = Usage()
    with pytest.raises(RecoverableChpmError, match="remains invalid"):
        await proposal_attempt.request(
            host,
            Settings(mode="live", actor_ids=["npc"]),
            usage,
            "Use the schema.",
            {},
            Draft,
            {},
            accept_choice,
        )
    assert model.requests[1][2]["proposal_feedback"]["repair_mode"] == "field_edits"
    assert usage.calls == 2 and usage.proposal_repairs == 1
