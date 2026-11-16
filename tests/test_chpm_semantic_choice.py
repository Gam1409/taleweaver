"""Live choices are explained preferences, independent of metadata tie seeds."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.engine.chpm import appraisal_context, motivation, semantic_choice
from backend.engine.chpm.host_state import record
from backend.engine.chpm.proposal_draft import Draft
from backend.engine.chpm.schema import ChoicePreference, Decision, KernelState, PreviousIntention
from tests.test_chpm_host_state import mind, source
from tests.test_chpm_kernel import observation, preferred_choice, wire_proposal


def fixture(preferred="CONTINUE"):
    value = mind()
    window = appraisal_context.build(value)
    catalogue = motivation.build(value, [], window)
    raw = wire_proposal()
    raw["candidates"]["DEFER"]["motives"] = deepcopy(raw["candidates"]["CONTINUE"]["motives"])
    raw["choice"] = preferred_choice(preferred=preferred)
    proposal = Draft.model_validate(raw).materialize(catalogue)
    return value, window, proposal, motivation.resolve(proposal, catalogue)


def choose(preferred="CONTINUE", *, changes=None, prior=None, observed=None):
    _, window, raw, motives = fixture(preferred)
    choice = ChoicePreference.model_validate({**raw.choice.model_dump(), **(changes or {})})
    return semantic_choice.select(
        "npc",
        observed or observation(),
        raw.canonical(),
        raw.question_gate,
        choice,
        motives,
        window,
        prior,
        context_hash="same-context",
    )


@pytest.mark.parametrize("preferred", ["CONTINUE", "DEFER"])
def test_preference_survives_message_and_session_id_changes_and_candidate_order(preferred):
    _, window, raw, motives = fixture(preferred)
    proposal = raw.canonical()
    for number in range(32):
        proposal.candidates.reverse()
        result = semantic_choice.select(
            "npc",
            observation(message_id=str(number), session_id=f"session-{number}"),
            proposal,
            raw.question_gate,
            raw.choice,
            motives,
            window,
            None,
            context_hash="same-context",
        )
        assert result.selected.kind == preferred
        assert result.policy_version == "motivated-choice-v2"
        assert Decision.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize(
    "changes",
    [
        {"preferred": "REFUSE"},
        {"motive_ids": ["foreign-memory"]},
        {"motive_ids": ["goal1", "goal1"]},
        {"continuity": "maintain"},
        {"continuity": "revise"},
    ],
)
def test_invalid_preference_has_no_hash_or_random_fallback(changes):
    with pytest.raises(ValueError):
        choose(changes=changes)


def test_missing_preference_is_not_silently_derived_from_array_order():
    raw = wire_proposal()
    raw.pop("choice")
    with pytest.raises(ValidationError, match="choice"):
        Draft.model_validate(raw)


def prior():
    selected = choose().selected
    return PreviousIntention(
        selected=selected,
        scene_id="room",
        source_message_id="reply",
        source_hash="reply-hash",
        spoken_evidence="Let us discuss it.",
    )


def test_previous_course_requires_maintain_or_source_grounded_revision():
    assert choose(prior=prior(), changes={"continuity": "maintain"}).selected.kind == "CONTINUE"
    with pytest.raises(ValueError, match="Account for"):
        choose(prior=prior())
    with pytest.raises(ValueError, match="kind"):
        choose("DEFER", prior=prior(), changes={"continuity": "maintain"})
    with pytest.raises(ValueError, match="exact accessible"):
        choose("DEFER", prior=prior(), changes={"continuity": "revise"})
    with pytest.raises(ValueError, match="unavailable"):
        choose(
            "DEFER",
            prior=prior(),
            changes={
                "continuity": "revise",
                "change_basis": [{"source_id": "hidden", "quote": "invented"}],
            },
        )


def initiation():
    value = prior()
    return value.model_copy(
        update={"selected": value.selected.model_copy(update={"kind": "INITIATE"})}
    )


def test_an_initiated_discussion_can_continue_without_invented_revision_evidence():
    previous = initiation()
    original = previous.model_dump_json()
    result = choose(prior=previous, changes={"continuity": "maintain"})
    assert result.selected.kind == "CONTINUE"
    assert result.previous_intention.selected.kind == "INITIATE"
    assert result.choice_preference.change_basis == []
    assert previous.model_dump_json() == original


def test_continuing_an_initiation_cannot_drop_its_existing_conditions():
    previous = initiation()
    previous.selected.preconditions = ["Wait until the player chooses a topic."]
    with pytest.raises(ValueError, match="preserve its conditions"):
        choose(prior=previous, changes={"continuity": "maintain"})


def test_continuing_an_initiation_still_cannot_claim_new_revision_evidence():
    with pytest.raises(ValueError, match="revision evidence"):
        choose(
            prior=initiation(),
            changes={
                "continuity": "maintain",
                "change_basis": [{"source_id": "e1", "quote": "A new demand."}],
            },
        )


@pytest.mark.parametrize("kind", ["REFUSE", "DEFER", "ACCEPT", "NEGOTIATE"])
def test_other_kind_changes_still_require_a_grounded_revision(kind):
    previous = prior()
    previous.selected.kind = kind
    with pytest.raises(ValueError, match="kind"):
        choose(prior=previous, changes={"continuity": "maintain"})


def test_continuation_to_a_new_initiative_still_requires_a_revision():
    _, window, raw, motives = fixture()
    proposal = raw.canonical()
    proposal.candidates.append(proposal.candidates[0].model_copy(update={"kind": "INITIATE"}))
    motives["INITIATE"] = motives["CONTINUE"]
    choice = raw.choice.model_copy(update={"preferred": "INITIATE", "continuity": "maintain"})
    with pytest.raises(ValueError, match="kind"):
        semantic_choice.select(
            "npc",
            observation(),
            proposal,
            None,
            choice,
            motives,
            window,
            prior(),
            context_hash="same",
        )


def test_exact_observed_response_can_change_course_without_rewriting_identity():
    value, _, raw, _ = fixture("DEFER")
    value = record(value, source("reaction", text="I need quiet now."), minute=1)
    window = appraisal_context.build(value)
    catalogue = motivation.build(value, [], window)
    motives = motivation.resolve(raw, catalogue)
    choice = raw.choice.model_copy(update={"continuity": "revise"})
    choice = ChoicePreference.model_validate(
        {
            **choice.model_dump(),
            "change_basis": [{"source_id": "e1", "quote": "I need quiet now."}],
        }
    )
    before = value.model_dump_json()
    result = semantic_choice.select(
        "npc",
        observation(),
        raw.canonical(),
        None,
        choice,
        motives,
        window,
        prior(),
        context_hash="x",
    )
    assert result.selected.kind == "DEFER"
    assert value.model_dump_json() == before


def test_continuity_requires_own_retained_delivered_speech_and_exact_revision():
    value, _, _, _ = fixture()
    speech = source("reply", text="Let us discuss it.").model_copy(
        update={
            "role": "assistant",
            "speaker_id": "npc",
            "content_hash": "reply-hash",
        }
    )
    value = record(value, speech, minute=1)
    previous = choose(observed=observation(message_id="old"))
    previous.status = "delivered"
    previous.reply_id, previous.reply_hash = "reply", "reply-hash"
    previous.spoken_evidence = speech.text
    assert semantic_choice.previous_context(value, previous, observation()) is not None
    for changes in (
        {"reply_revision": "changed"},
        {"reply_hash": "stale"},
        {"actor_id": "other"},
        {"status": "selected"},
        {"spoken_evidence": "invented"},
    ):
        assert (
            semantic_choice.previous_context(
                value, previous.model_copy(update=changes), observation()
            )
            is None
        )
    assert semantic_choice.previous_context(mind(), previous, observation()) is None


def test_saved_envelope_migrates_without_reselecting_old_decisions():
    raw = KernelState().model_dump()
    raw["schema_version"] = 4
    assert KernelState.model_validate(raw).schema_version == 6
    assert raw["schema_version"] == 4
    result = choose()
    broken = result.model_dump()
    broken["choice_preference"]["preferred"] = "DEFER"
    with pytest.raises(ValidationError, match="differs"):
        Decision.model_validate(broken)


def test_explicit_goal_label_cannot_override_a_grounded_personal_preference():
    value, window, _, _ = fixture()
    catalogue = motivation.build(value, [], window)
    raw = wire_proposal()
    raw["candidates"]["CONTINUE"]["motives"][0]["motive_id"] = "character"
    raw["candidates"]["DEFER"]["motives"][0]["motive_id"] = "goal1"
    raw["choice"]["motive_ids"] = ["character"]
    proposal = Draft.model_validate(raw).materialize(catalogue)
    result = semantic_choice.select(
        "npc",
        observation(),
        proposal.canonical(),
        None,
        proposal.choice,
        motivation.resolve(proposal, catalogue),
        window,
        None,
        context_hash="same",
    )
    assert result.selected.kind == "CONTINUE"
    assert result.selected.goal_alignment == "unknown"
    assert proposal.candidates["DEFER"].goal_alignment == "supports"


def test_source_set_dominance_is_audited_without_pretending_to_measure_preference():
    value, window, raw, _ = fixture()
    data = wire_proposal(raw)
    data["candidates"]["DEFER"]["motives"].append(
        {
            "motive_id": "character",
            "effect": "supports",
            "relevance": "An additional possible consideration.",
        }
    )
    catalogue = motivation.build(value, [], window)
    proposal = Draft.model_validate(data).materialize(catalogue)
    result = semantic_choice.select(
        "npc",
        observation(),
        proposal.canonical(),
        None,
        proposal.choice,
        motivation.resolve(proposal, catalogue),
        window,
        None,
        context_hash="same",
    )
    assert result.selected.kind == "CONTINUE"
    assert result.motive_dominance["CONTINUE"] == ["DEFER"]


def test_unresolved_question_dependencies_still_block_conditional_actions():
    value, window, raw, _ = fixture()
    data = wire_proposal(raw)
    data["candidates"]["CLARIFY"] = deepcopy(data["candidates"]["CONTINUE"])
    data["candidates"]["CLARIFY"]["intention"] = "Ask whether the player wants to discuss the plan."
    data["question_gate"] = {
        "kind": "player_intention",
        "missing_fact": "Does the player want to discuss the plan?",
        "branches": [{"answer": "Yes", "action": "CONTINUE"}, {"answer": "No", "action": "DEFER"}],
    }
    catalogue = motivation.build(value, [], window)
    proposal = Draft.model_validate(data).materialize(catalogue)
    args = ("npc", observation(), proposal.canonical(), proposal.question_gate)
    tail = (motivation.resolve(proposal, catalogue), window, None)
    with pytest.raises(ValueError, match="unresolved"):
        semantic_choice.select(*args, proposal.choice, *tail, context_hash="same")
    choice = proposal.choice.model_copy(update={"preferred": "CLARIFY"})
    assert (
        semantic_choice.select(*args, choice, *tail, context_hash="same").selected.kind == "CLARIFY"
    )
