"""Autonomy is a selection policy, not a request for a less cautious prose style."""

import pytest
from pydantic import ValidationError

from backend.engine.chpm.initiative import select
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.schema import Candidate, Decision, Proposal, QuestionGate
from tests.test_chpm_kernel import observation

GOAL = "Repair the bridge"


def candidate(kind, alignment="supports"):
    return Candidate(
        kind=kind,
        intention=f"Choose {kind}",
        goal_alignment=alignment,
        goal_quote=GOAL if alignment in {"supports", "conflicts"} else "",
        reconsider_if="The inspection result changes",
    )


def choose(candidates, gate=None):
    return select(
        "npc",
        observation(),
        Proposal(candidates=candidates, appraisal="Uncertain"),
        gate,
        goal=GOAL,
        context_hash="context",
    )


def gate(**changes):
    return QuestionGate.model_validate(
        {
            "kind": "external_fact",
            "missing_fact": "Has the authorized inspection passed?",
            "branches": [
                {"answer": "Yes", "action": "ACCEPT"},
                {"answer": "No", "action": "REFUSE"},
            ],
            **changes,
        }
    )


@pytest.mark.parametrize("kind", ["CONTINUE", "INITIATE", "ACCEPT", "REFUSE", "NEGOTIATE", "DEFER"])
def test_question_without_decision_gap_cannot_win_by_claiming_goal_support(kind):
    result = choose([candidate("CLARIFY"), candidate(kind, "neutral")])
    assert result.selected.kind == kind
    assert result.policy_version == "initiative-gated-v1"
    assert "no explicit" in result.selection_reasons[0]
    assert Decision.model_validate_json(result.model_dump_json()) == result


def test_missing_external_fact_can_authorize_a_necessary_question():
    result = choose([candidate("CLARIFY"), candidate("ACCEPT"), candidate("REFUSE")], gate())
    assert result.selected.kind == "CLARIFY"
    assert result.question_gate == gate()


def test_independent_progress_wins_even_with_a_valid_question_gate():
    result = choose(
        [candidate("CLARIFY"), candidate("ACCEPT"), candidate("REFUSE"), candidate("INITIATE")],
        gate(),
    )
    assert result.selected.kind == "INITIATE"
    assert "independent intention" in result.selection_reasons[-1]


def test_low_priority_chitchat_does_not_replace_a_necessary_high_priority_question():
    result = choose(
        [
            candidate("CLARIFY"),
            candidate("ACCEPT"),
            candidate("REFUSE"),
            candidate("CONTINUE", "neutral"),
        ],
        gate(),
    )
    assert result.selected.kind == "CLARIFY"


@pytest.mark.parametrize(
    "branches",
    [
        [{"answer": "Yes", "action": "ACCEPT"}, {"answer": "No", "action": "INITIATE"}],
        [{"answer": "Yes", "action": "ACCEPT"}, {"answer": "No", "action": "ACCEPT"}],
        [{"answer": "Yes", "action": "ACCEPT"}, {"answer": "yes", "action": "REFUSE"}],
        [{"answer": "Yes", "action": "CLARIFY"}, {"answer": "No", "action": "REFUSE"}],
    ],
)
def test_invented_or_redundant_conditional_choices_do_not_unlock_question(branches):
    result = choose(
        [candidate("CLARIFY"), candidate("ACCEPT"), candidate("REFUSE")], gate(branches=branches)
    )
    assert result.selected.kind != "CLARIFY"
    assert "did not identify" in result.selection_reasons[0]


def test_player_choices_are_not_made_on_their_behalf():
    question = gate(
        kind="player_intention", missing_fact="Does the player want to join the proposed repair?"
    )
    result = choose([candidate("CLARIFY"), candidate("ACCEPT"), candidate("REFUSE")], question)
    assert result.selected.kind == "CLARIFY"
    with pytest.raises(ValidationError):
        gate(kind="permission_to_continue")


def test_unanswerable_conflict_does_not_execute_a_conditional_action_as_if_fact_were_known():
    with pytest.raises(ChpmError, match="conflicts"):
        choose(
            [candidate("CLARIFY", "conflicts"), candidate("ACCEPT"), candidate("REFUSE")], gate()
        )


def test_avoiding_questions_never_forces_goal_conflicting_compliance():
    with pytest.raises(ChpmError, match="goal-conflicting"):
        choose([candidate("CLARIFY"), candidate("ACCEPT", "conflicts")])


def test_question_gate_does_not_turn_all_authored_goals_into_absolute_prohibitions():
    result = choose([candidate("INITIATE", "conflicts"), candidate("CONTINUE", "conflicts")])
    assert result.selected.kind in {"INITIATE", "CONTINUE"}
