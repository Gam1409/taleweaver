"""Shared proposal/selection boundary for session turns and isolated evaluations."""

from typing import Any

from backend.engine.chpm import (
    agenda,
    appraisal,
    cognitive_context,
    experience,
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
    instruction = prompts.PROPOSE + INSTRUCTIONS + motivation.INSTRUCTIONS + experience.INSTRUCTIONS
    window, motives, payload, identifiers = cognitive_context.pack(
        mind, observation, supplied, entries, settings, instruction
    )
    key = fingerprint(payload)
    cached = existing(previous, observation, key)
    if cached is not None:
        return cached, mind
    raw = await inference.request(
        manager,
        settings,
        usage,
        instruction,
        payload,
        GroundedProposal,
        "proposal",
        identifiers=identifiers,
    )
    resolved_motives = motivation.resolve(raw, motives)
    changed, accepted_ids = appraisal.accept(
        mind, raw.interpretations, window, message_id=observation.message_id
    )
    changed, experience_ids = experience.accept(
        changed, raw.experiences, window, motives, message_id=observation.message_id
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
        motives=resolved_motives,
    )
    decision.interpretation_ids = accepted_ids
    decision.experience_ids = experience_ids
    decision.motivation_policy = motivation.POLICY
    decision.candidate_motives = resolved_motives
    return decision, changed
