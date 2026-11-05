"""Shared proposal/selection boundary for session turns and isolated evaluations."""

from typing import Any

from backend.engine.chpm import (
    agenda,
    appraisal,
    appraisal_context,
    inference,
    initiative,
    motivation,
    prompts,
)
from backend.engine.chpm.appraisal_contracts import INSTRUCTIONS, GroundedProposal
from backend.engine.chpm.host_state import Mind
from backend.engine.chpm.kernel import existing, fingerprint, select
from backend.engine.chpm.schema import (
    AgendaEntry,
    Decision,
    Observation,
    Proposal,
    ProposalOptions,
    Settings,
    Usage,
)


async def decide(
    manager: Any,
    settings: Settings,
    usage: Usage,
    actor_id: str,
    observation: Observation,
    supplied: dict,
    entries: list[AgendaEntry],
    previous: Decision | None = None,
) -> Decision:
    key = fingerprint(supplied)
    cached = existing(previous, observation, key)
    if cached is not None:
        return cached
    raw: ProposalOptions | Proposal = await inference.request(
        manager, settings, usage, prompts.PROPOSE, supplied, ProposalOptions, "proposal"
    )
    proposal = raw.canonical() if isinstance(raw, ProposalOptions) else raw
    agenda.validate_proposal(proposal, entries)
    return select(actor_id, observation, proposal, goal=supplied["authored_goal"], context_hash=key)


async def deliberate(
    manager: Any,
    settings: Settings,
    usage: Usage,
    actor_id: str,
    observation: Observation,
    supplied: dict,
    entries: list[AgendaEntry],
    mind: Mind,
    previous: Decision | None = None,
) -> tuple[Decision, Mind]:
    # Only perceived speech can cue recall, never the player's unobserved narration.
    cues = " ".join(
        source.text
        for source in mind.sources.values()
        if source.message_id == observation.message_id and source.kind in {"speech", "world_event"}
    )
    window = appraisal_context.build(mind, query=cues)
    motives = motivation.build(mind, entries, window)
    identifiers = window.identifiers()
    identifiers["motive_id"] = list(motives.sources)
    goals = mind.genesis.identity.authored_goals
    if all(len(goal) <= 300 for goal in goals):
        identifiers["goal_quote"] = ["", *goals]
    payload = {
        **supplied,
        "appraisal_context": window.payload,
        "motivation_context": motives.payload(),
    }
    key = fingerprint(payload)
    cached = existing(previous, observation, key)
    if cached is not None:
        return cached, mind
    raw = await inference.request(
        manager,
        settings,
        usage,
        prompts.PROPOSE + INSTRUCTIONS + motivation.INSTRUCTIONS,
        payload,
        GroundedProposal,
        "proposal",
        identifiers=identifiers,
    )
    resolved_motives = motivation.resolve(raw, motives)
    changed, accepted_ids = appraisal.accept(
        mind, raw.interpretations, window, message_id=observation.message_id
    )
    proposal = raw.canonical()
    agenda.validate_proposal(proposal, entries)
    decision = initiative.select(
        actor_id,
        observation,
        proposal,
        raw.question_gate,
        goal=supplied["authored_goal"],
        context_hash=key,
    )
    decision.interpretation_ids = accepted_ids
    decision.motivation_policy = motivation.POLICY
    decision.candidate_motives = resolved_motives
    return decision, changed
