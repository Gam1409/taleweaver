"""A versioned question gate: useful independent intentions take priority over stalling."""

from backend.engine.chpm import preference
from backend.engine.chpm.kernel import ChpmError, digest
from backend.engine.chpm.kernel import select as goal_select
from backend.engine.chpm.motivation_contracts import ResolvedMotive
from backend.engine.chpm.schema import (
    ActionKind,
    Candidate,
    Decision,
    Observation,
    Proposal,
    QuestionGate,
)

PRIORITY = {"supports": 0, "neutral": 1, "unknown": 1, "conflicts": 2}


def select(
    actor_id: str,
    observed: Observation,
    proposal: Proposal,
    gate: QuestionGate | None,
    *,
    goal: str,
    context_hash: str,
    motives: dict[ActionKind, list[ResolvedMotive]] | None = None,
) -> Decision:
    # Reuse all canonical candidate/goal checks; persist the full offered set.
    result = goal_select(actor_id, observed, proposal, goal=goal, context_hash=context_hash)
    choices: dict[str, Candidate] = {candidate.kind: candidate for candidate in proposal.candidates}
    independent = [candidate for candidate in proposal.candidates if candidate.kind != "CLARIFY"]
    if not independent:
        raise ChpmError("CHPM proposal offers no independent dialogue alternative.")
    blocked, reason = question_blocks(choices, gate)
    reasons = [reason]
    comparisons: dict[ActionKind, list[ActionKind]] = {}
    free = [candidate for candidate in independent if candidate.kind not in blocked]
    conditional = [candidate for candidate in independent if candidate.kind in blocked]
    useful_free = bool(free) and (
        not conditional
        or min(PRIORITY[c.goal_alignment] for c in free)
        <= min(PRIORITY[c.goal_alignment] for c in conditional)
    )
    if useful_free:
        chosen = _best(free, observed, motives, comparisons)
        reason = "An independent intention can serve the goal without asking for an answer."
    elif blocked and choices["CLARIFY"].goal_alignment != "conflicts":
        chosen = choices["CLARIFY"]
        reason = "The missing fact separates two proposed actions; no equally useful independent action is available."
    else:
        if not free:
            raise ChpmError(
                "CHPM has no independent intention and its clarification conflicts with the goal."
            )
        chosen = _best(free, observed, motives, comparisons)
    if (
        chosen.goal_alignment == "conflicts"
        and "CLARIFY" in choices
        and choices["CLARIFY"].goal_alignment != "conflicts"
    ):
        raise ChpmError(
            "CHPM cannot replace an unsupported question with a goal-conflicting intention."
        )
    result.selected = chosen.model_copy(deep=True)
    result.policy_version = "motive-frontier-v1" if motives is not None else "initiative-gated-v1"
    result.selection_reasons = [*reasons, reason] if reasons[0] != reason else reasons
    result.question_gate = gate.model_copy(deep=True) if gate else None
    if motives is not None:
        result.motivation_policy = "source-grounded-v1"
        result.candidate_motives = motives
        result.motive_dominance = comparisons
        result.selection_reasons.append(
            "Equally goal-aligned eligible options use personal-motive dominance; "
            "incomparable ties use a deterministic hash, not calibrated psychological utility."
        )
    return result


def question_blocks(
    choices: dict[str, Candidate], gate: QuestionGate | None
) -> tuple[set[str], str]:
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


def _best(
    candidates: list[Candidate],
    observed: Observation,
    motives: dict[ActionKind, list[ResolvedMotive]] | None,
    comparisons: dict[ActionKind, list[ActionKind]],
) -> Candidate:
    best_priority = min(PRIORITY[c.goal_alignment] for c in candidates)
    candidates = [c for c in candidates if PRIORITY[c.goal_alignment] == best_priority]
    if motives is not None:
        compared = preference.compare(candidates, motives)
        comparisons.update(compared)
        candidates = [c for c in candidates if not compared[c.kind]]
    return min(
        candidates,
        key=lambda candidate: (
            PRIORITY[candidate.goal_alignment],
            digest(observed.session_id + ":" + observed.message_id + ":" + candidate.kind),
        ),
    )
