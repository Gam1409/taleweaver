"""Shared proposal/selection boundary for session turns and isolated evaluations."""

from typing import Any

from backend.engine.chpm import (
    agenda,
    agent,
    agent_context,
    appraisal,
    belief_recall,
    development,
    development_request,
    experience,
    inference,
    motivation,
    prompts,
    proposal_attempt,
    proposal_draft,
    semantic_choice,
)
from backend.engine.chpm.appraisal_contracts import INSTRUCTIONS
from backend.engine.chpm.development_contracts import DevelopmentProposal
from backend.engine.chpm.host_state import Mind
from backend.engine.chpm.kernel import ChpmError, existing, fingerprint, select
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
    if mind.genesis.scope.observer_id != actor_id:
        raise ChpmError("CHPM cognition belongs to another NPC.")
    prior = semantic_choice.previous_context(mind, previous, observation)
    names = getattr(getattr(manager, "_chpm_turn", None), "present_names", {})
    focus = belief_recall.subjects(mind, observation.player_request, observation.message_id, names)
    supplied = {
        **supplied,
        "proposal_contract": "motivated-choice-v2",
        "appraisal_contract": "split-beliefs-v1",
        "previous_intention": prior.model_dump() if prior else None,
    }
    pinned = {}
    pinned_beliefs = {}
    audit: list[dict] = []
    if settings.agent_steps and settings.mode == "live":
        tools, audit = await agent.investigate(
            manager, settings, usage, mind, observation, supplied
        )
        mind, pinned = tools.mind, tools.pins
        pinned_beliefs = tools.beliefs
        supplied = {
            **supplied,
            "agent_contract": "source-handoff-v1",
            "agent_plan_status": [step["stop"] for step in audit],
            "agent_lookup_status": [
                {"tool": request["tool"], "status": result["status"]}
                for step in audit
                for request, result in zip(step["requests"], step["results"], strict=True)
            ],
        }
    instruction = (
        prompts.PROPOSE
        + INSTRUCTIONS
        + motivation.INSTRUCTIONS
        + experience.INSTRUCTIONS
        + semantic_choice.INSTRUCTIONS
        + "\nThe host derives goal_alignment and goal_quote from cited goal motives. Omit these two fields; retain all conflicting motives."
    )
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
        pinned=pinned,
        pinned_beliefs=pinned_beliefs,
        focus_subjects=focus,
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
        decision = semantic_choice.select(
            actor_id,
            observation,
            proposal,
            raw.question_gate,
            raw.choice,
            resolved_motives,
            window,
            prior,
            context_hash=key,
        )
        # Assignment/model_copy do not re-run validators on mutable contracts.
        # Check the complete handoff while the proposal is still turn-local.
        complete = Decision.model_validate(
            {
                **decision.model_dump(),
                "agent_audit": audit,
                "agent_evidence": agent_context.collect(pinned, observation),
                "interpretation_ids": accepted_ids,
                "experience_ids": experience_ids,
                "development_ids": development_ids,
                "development_status": development_status,
                "motivation_policy": motivation.POLICY,
                "candidate_motives": resolved_motives,
            }
        )
        return complete, changed

    return await proposal_attempt.request(
        manager,
        settings,
        usage,
        instruction,
        payload,
        proposal_draft.DevelopmentDraft if schema is DevelopmentProposal else proposal_draft.Draft,
        identifiers,
        accept,
    )
