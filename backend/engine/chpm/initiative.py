"""A versioned question gate: useful independent intentions take priority over stalling."""

from backend.engine.chpm.kernel import ChpmError, digest
from backend.engine.chpm.kernel import select as goal_select
from backend.engine.chpm.schema import Candidate, Decision, Observation, Proposal, QuestionGate

PRIORITY = {"supports": 0, "neutral": 1, "unknown": 1, "conflicts": 2}


def select(
    actor_id: str,
    observed: Observation,
    proposal: Proposal,
    gate: QuestionGate | None,
    *,
    goal: str,
    context_hash: str,
) -> Decision:
    # Reuse all canonical candidate/goal checks; persist the full offered set.
    result = goal_select(actor_id, observed, proposal, goal=goal, context_hash=context_hash)
    choices: dict[str, Candidate] = {candidate.kind: candidate for candidate in proposal.candidates}
    independent = [candidate for candidate in proposal.candidates if candidate.kind != "CLARIFY"]
    if not independent:
        raise ChpmError("CHPM proposal offers no independent dialogue alternative.")
    blocked, reason = _blocked(choices, gate)
    reasons = [reason]
    free = [candidate for candidate in independent if candidate.kind not in blocked]
    conditional = [candidate for candidate in independent if candidate.kind in blocked]
    useful_free = bool(free) and (
        not conditional
        or min(PRIORITY[c.goal_alignment] for c in free)
        <= min(PRIORITY[c.goal_alignment] for c in conditional)
    )
    if useful_free:
        chosen = _best(free, observed)
        reason = "An independent intention can serve the goal without asking for an answer."
    elif blocked and choices["CLARIFY"].goal_alignment != "conflicts":
        chosen = choices["CLARIFY"]
        reason = "The missing fact separates two proposed actions; no equally useful independent action is available."
    else:
        if not free:
            raise ChpmError(
                "CHPM has no independent intention and its clarification conflicts with the goal."
            )
        chosen = _best(free, observed)
    if (
        chosen.goal_alignment == "conflicts"
        and "CLARIFY" in choices
        and choices["CLARIFY"].goal_alignment != "conflicts"
    ):
        raise ChpmError(
            "CHPM cannot replace an unsupported question with a goal-conflicting intention."
        )
    result.selected = chosen.model_copy(deep=True)
    result.policy_version = "initiative-gated-v1"
    result.selection_reasons = [*reasons, reason] if reasons[0] != reason else reasons
    result.question_gate = gate.model_copy(deep=True) if gate else None
    return result


def _blocked(choices: dict[str, Candidate], gate: QuestionGate | None) -> tuple[set[str], str]:
    if "CLARIFY" not in choices:
        return set(), "No clarification was proposed."
    if gate is None:
        return set(), "Clarification had no explicit decision-changing information gap."
    actions = {branch.action for branch in gate.branches}
    answers = {branch.answer.casefold() for branch in gate.branches}
    if (
        len(actions) != 2
        or len(answers) != 2
        or "CLARIFY" in actions
        or not actions <= choices.keys()
    ):
        return set(), "Clarification did not identify two distinct available conditional actions."
    return set(actions), "Conditional alternatives require the missing fact."


def _best(candidates: list[Candidate], observed: Observation) -> Candidate:
    return min(
        candidates,
        key=lambda candidate: (
            PRIORITY[candidate.goal_alignment],
            digest(observed.session_id + ":" + observed.message_id + ":" + candidate.kind),
        ),
    )
