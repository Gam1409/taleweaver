"""Shared proposal/selection boundary for session turns and isolated evaluations."""

from typing import Any

from backend.engine.chpm import (
    agenda,
    appraisal,
    development,
    development_request,
    experience,
    inference,
    initiative,
    motivation,
    prompts,
    proposal_attempt,
    proposal_draft,
)
from backend.engine.chpm.appraisal_contracts import INSTRUCTIONS
from backend.engine.chpm.development_contracts import DevelopmentProposal
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
        manager,
        settings,
        usage,
        prompts.PROPOSE
        + "\nGoal alignment supports/conflicts requires an exact authored_goal quote; neutral/unknown uses an empty quote.",
        supplied,
        ProposalOptions,
        "proposal",
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
    supplied = {**supplied, "proposal_contract": "grounded-intents-v2"}
    instruction = prompts.PROPOSE + INSTRUCTIONS + motivation.INSTRUCTIONS + experience.INSTRUCTIONS
    (
        window,
        motives,
        payload,
        identifiers,
        schema,
        instruction,
        development_sources,
        development_status,
    ) = development_request.prepare(
        mind,
        observation,
        supplied,
        entries,
        settings.model_copy(update={"max_input_chars": settings.max_input_chars - 2048}),
        instruction,
    )
    key = fingerprint(payload)
    cached = existing(previous, observation, key)
    if cached is not None:
        return cached, mind

    def accept(draft: proposal_draft.Draft) -> tuple[Decision, Mind]:
        raw = draft.materialize(motives)
        resolved_motives = motivation.resolve(raw, motives)
        changed, accepted_ids = appraisal.accept(
            mind, raw.interpretations, window, message_id=observation.message_id
        )
        changed, experience_ids = experience.accept(
            changed, raw.experiences, window, motives, message_id=observation.message_id
        )
        changed, development_ids = development.accept(
            changed,
            raw.developments if isinstance(raw, DevelopmentProposal) else [],
            development_sources,
            message_id=observation.message_id,
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
        decision.development_ids = development_ids
        decision.development_status = development_status
        decision.motivation_policy = motivation.POLICY
        decision.candidate_motives = resolved_motives
        return decision, changed

    return await proposal_attempt.request(
        manager,
        settings,
        usage,
        instruction
        + "\nThe host derives goal_alignment and goal_quote from cited goal motives. Omit these two fields; retain all conflicting motives.",
        payload,
        proposal_draft.DevelopmentDraft if schema is DevelopmentProposal else proposal_draft.Draft,
        identifiers,
        accept,
    )
