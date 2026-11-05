"""Pure selection and replay fences; LLM appraisals remain fallible proposals."""

import hashlib
import json

from backend.engine.chpm.schema import Candidate, Decision, Observation, Proposal


class ChpmError(ValueError):
    """A visible failure; callers must not silently replace a live decision."""


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def fingerprint(value: dict) -> str:
    return digest(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")))


def existing(
    previous: Decision | None, observation: Observation, context_hash: str
) -> Decision | None:
    if previous is None or previous.observation.session_id != observation.session_id:
        return None
    old = previous.observation
    if old.message_id == observation.message_id:
        if old != observation or previous.context_hash != context_hash:
            raise ChpmError("CHPM source changed. Replay the complete turn before retrying.")
        return previous.model_copy(deep=True)
    if observation.turn_revision is not None and old.turn_revision is not None:
        if observation.turn_revision <= old.turn_revision:
            raise ChpmError("CHPM rejected an observation older than its current state.")
        return None
    if observation.sequence < old.sequence:
        raise ChpmError("CHPM rejected an observation older than its current state.")
    if observation.sequence == old.sequence and observation.turn_revision is None:
        raise ChpmError("CHPM observation order is ambiguous without a host turn revision.")
    return None


def _rank(candidate: Candidate, observation: Observation) -> tuple[int, str]:
    # Unknown is not evidence of either support or conflict. No random choice or
    # dependence on generation order; authored goals are defeasible pilot inputs.
    ranks = {"supports": 0, "neutral": 1, "unknown": 1, "conflicts": 2}
    tie = digest(observation.session_id + ":" + observation.message_id + ":" + candidate.kind)
    return ranks[candidate.goal_alignment], tie


def select(
    actor_id: str,
    observation: Observation,
    proposal: Proposal,
    *,
    goal: str,
    context_hash: str,
) -> Decision:
    kinds = [candidate.kind for candidate in proposal.candidates]
    if len(kinds) != len(set(kinds)):
        raise ChpmError("CHPM candidates repeat the same action kind.")
    for candidate in proposal.candidates:
        _validate_grounding(candidate, goal)
    chosen = min(proposal.candidates, key=lambda candidate: _rank(candidate, observation))
    return Decision(
        actor_id=actor_id,
        observation=observation,
        context_hash=context_hash,
        proposal=proposal.model_copy(deep=True),
        selected=chosen.model_copy(deep=True),
    )


def _validate_grounding(candidate: Candidate, goal: str) -> None:
    if candidate.goal_alignment in {"supports", "conflicts"}:
        if not candidate.goal_quote or candidate.goal_quote not in goal:
            raise ChpmError("CHPM goal alignment has no exact authored-goal evidence.")
    elif candidate.goal_quote:
        raise ChpmError("Neutral or unknown alignment must not claim goal evidence.")
