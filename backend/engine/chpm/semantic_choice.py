"""Source-bound model preference replaces metadata tie-breaking for live cognition."""

from backend.engine.chpm import choice_grounds, initiative, preference
from backend.engine.chpm.appraisal_context import Window
from backend.engine.chpm.host_state import Mind
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.motivation_contracts import ResolvedMotive
from backend.engine.chpm.schema import (
    ActionKind,
    Candidate,
    ChoicePreference,
    Decision,
    Observation,
    PreviousIntention,
    Proposal,
    QuestionGate,
)


def previous_context(
    mind: Mind, previous: Decision | None, observed: Observation
) -> PreviousIntention | None:
    if previous is None or previous.status != "delivered":
        return None
    if (previous.actor_id, previous.observation.session_id) != (
        mind.genesis.scope.observer_id,
        observed.session_id,
    ) or previous.observation.message_id == observed.message_id:
        return None
    valid = any(
        source.message_id == previous.reply_id
        and source.content_hash == previous.reply_hash
        and source.revision_id == previous.reply_revision
        and source.speaker_id == previous.actor_id
        and source.role == "assistant"
        and previous.spoken_evidence
        and previous.spoken_evidence in source.text
        for source in mind.sources.values()
    )
    if not valid:
        return None
    return PreviousIntention(
        selected=previous.selected,
        scene_id=previous.observation.scene_id,
        source_message_id=str(previous.reply_id),
        source_hash=str(previous.reply_hash),
        source_revision_id=previous.reply_revision,
        spoken_evidence=previous.spoken_evidence,
    )


def eligible(proposal: Proposal, gate: QuestionGate | None) -> tuple[list[Candidate], str]:
    choices: dict[str, Candidate] = {candidate.kind: candidate for candidate in proposal.candidates}
    if len(choices) != len(proposal.candidates):
        raise ChpmError("CHPM candidates repeat the same action kind.")
    independent = [c for c in proposal.candidates if c.kind != "CLARIFY"]
    if not independent:
        raise ChpmError("CHPM proposal offers no independent dialogue alternative.")
    blocked, reason = initiative.question_blocks(choices, gate)
    free = [c for c in independent if c.kind not in blocked]
    # Goal labels and source-set dominance describe tradeoffs; they are not
    # calibrated psychological preferences and cannot veto a grounded choice.
    if blocked:
        free.append(choices["CLARIFY"])
    if not free:
        raise ChpmError("No independent or justified clarifying intention is available.")
    return free, reason


def select(
    actor_id: str,
    observed: Observation,
    proposal: Proposal,
    gate: QuestionGate | None,
    choice: ChoicePreference | None,
    motives: dict[ActionKind, list[ResolvedMotive]],
    window: Window,
    prior: PreviousIntention | None,
    *,
    context_hash: str,
) -> Decision:
    if choice is None:
        raise ChpmError("A live proposal must state its source-grounded preferred intention.")
    candidates, reason = eligible(proposal, gate)
    comparisons = preference.compare(candidates, motives)
    allowed = {c.kind: c for c in candidates}
    if choice.preferred not in allowed:
        raise ChpmError(
            "Preferred intention is unoffered or depends on an unresolved question. "
            + "Eligible keys: "
            + ", ".join(sorted(allowed))
            + "."
        )
    selected = allowed[choice.preferred]
    if (
        prior
        and choice.continuity == "maintain"
        and selected.preconditions != prior.selected.preconditions
    ):
        raise ChpmError(
            "Maintaining an intention must preserve its conditions; revise explicitly with new evidence."
        )
    cited = {m.source.id: m for m in motives[selected.kind]}
    choice_grounds.validate(choice.preferred, choice.motive_ids, cited.keys())
    if not any(
        cited[key].effect == "supports"
        and cited[key].source.subject_id == actor_id
        and cited[key].source.status in {"authored", "declared"}
        for key in choice.motive_ids
    ):
        raise ChpmError("Choice needs the NPC's own supporting motive, not just a player's demand.")
    _continuity(choice, prior, window)
    return Decision(
        actor_id=actor_id,
        observation=observed,
        context_hash=context_hash,
        proposal=proposal,
        selected=selected.model_copy(deep=True),
        policy_version="motivated-choice-v2",
        choice_preference=choice,
        previous_intention=prior,
        question_gate=gate,
        candidate_motives=motives,
        motivation_policy="source-grounded-v1",
        motive_dominance=comparisons,
        selection_reasons=[
            reason,
            "The model explicitly preferred this eligible, source-grounded intention; message IDs do not rank alternatives.",
        ],
    )


def _continuity(choice: ChoicePreference, prior: PreviousIntention | None, window: Window) -> None:
    if prior is None:
        if choice.continuity != "new" or choice.change_basis:
            raise ChpmError(
                "No retained delivered intention exists; use continuity=new without change grounds."
            )
        return
    if choice.continuity == "new":
        raise ChpmError("Account for the retained intention: maintain it or explain a revision.")
    if choice.continuity == "maintain":
        same_kind = choice.preferred == prior.selected.kind
        continuing_initiation = (prior.selected.kind, choice.preferred) == ("INITIATE", "CONTINUE")
        if (not same_kind and not continuing_initiation) or choice.change_basis:
            raise ChpmError(
                "Maintaining an intention permits only the same kind or INITIATE to CONTINUE, "
                "without claiming revision evidence."
            )
        return
    if not choice.change_basis:
        raise ChpmError("A changed intention needs exact accessible evidence and an explanation.")
    for basis in choice.change_basis:
        source = window.sources.get(basis.source_id)
        if source is None or basis.quote not in source[2]:
            raise ChpmError("Changed intention cites unavailable or inexact evidence.")


INSTRUCTIONS = """
CHOICE: Return choice.preferred (candidate key), motive_ids (distinct motive_id values
copied from candidates[preferred].motives, including personal support), reason
(brief situational tradeoff), continuity and
change_basis (exact source_id/quote pairs). Choose what this NPC prefers now.
Goal alignment and motive counts are annotations, not automatic rankings. Explain
why the selected personal motive matters more here, including real tradeoffs.
Respect question-gate dependencies; never execute an unresolved conditional action.
Without previous_intention use continuity=new, change_basis=[]. Otherwise maintain
the actual course, not just its label, or revise with evidence explaining WHY NOW.
Context, a partner's response, grounded feelings or recalled experience may matter.
Unchanged pressure alone need not change the NPC's choice. Old intentions are not
completed acts, permanent roles or binding consent. Never invent a reason to switch.
"""
