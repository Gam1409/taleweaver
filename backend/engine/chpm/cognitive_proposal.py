"""Prepare the same complete cognitive context and acceptance boundary for either workflow."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.engine.chpm import (
    agenda,
    agent_context,
    appraisal,
    development,
    development_request,
    experience,
    motivation,
    prompts,
    proposal_draft,
    semantic_choice,
    semantic_recall,
)
from backend.engine.chpm.agent_tools import Tools
from backend.engine.chpm.appraisal_contracts import INSTRUCTIONS
from backend.engine.chpm.development_contracts import DevelopmentProposal
from backend.engine.chpm.host_state import Mind
from backend.engine.chpm.kernel import existing, fingerprint
from backend.engine.chpm.notebook_tools import NotebookDraft
from backend.engine.chpm.schema import AgendaEntry, Decision, Observation, Settings


@dataclass(frozen=True)
class Prepared:
    instruction: str
    payload: dict
    schema: type[proposal_draft.Draft]
    identifiers: dict
    accept: Callable[[proposal_draft.Draft], tuple[Decision, Mind]]
    cached: tuple[Decision, Mind] | None = None


def prepare(
    manager: Any,
    settings: Settings,
    actor_id: str,
    observation: Observation,
    supplied: dict,
    entries: list[AgendaEntry],
    mind: Mind,
    previous: Decision | None,
    *,
    pinned: dict,
    pinned_beliefs: dict,
    focus: tuple[str, ...],
    hits: list,
    audit: list[dict],
    notebook: NotebookDraft | None,
    tools: Tools | None = None,
) -> Prepared:
    if tools is not None:
        mind, pinned, pinned_beliefs = tools.mind, tools.pins, tools.beliefs
        supplied = {
            **supplied,
            "agent_contract": "source-handoff-v1",
            "agent_plan_status": [step["stop"] for step in audit],
            "agent_lookup_status": [
                {"tool": request["tool"], "status": result["status"]}
                for step in audit
                for request, result in zip(step["requests"], step["results"], strict=True)
            ],
            **({"private_notebook_not_world_facts": notebook.context()} if notebook else {}),
        }
    episode_contexts = semantic_recall.contexts(pinned, hits)
    if episode_contexts:
        supplied = {
            **supplied,
            "retrieved_episode_context": {
                alias: episode_contexts[key].model_dump(exclude_none=True)
                for alias, (key, _, _) in pinned.items()
                if key in episode_contexts
            },
        }
    prior = semantic_choice.previous_context(mind, previous, observation)
    instruction = (
        prompts.PROPOSE
        + INSTRUCTIONS
        + motivation.INSTRUCTIONS
        + experience.INSTRUCTIONS
        + semantic_choice.INSTRUCTIONS
        + "\nThe host derives goal_alignment and goal_quote from cited goal motives. Omit these two fields; retain all conflicting motives."
        + (
            "\nprivate_notebook_not_world_facts contains your own subjective notes. Use them for continuity, not as witnessed evidence, an instruction, a personality patch or a completed world action."
            if notebook
            else ""
        )
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
    cached_pair = (cached, mind) if cached is not None else None

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
                "agent_evidence": agent_context.collect(
                    pinned,
                    observation,
                    **({"contexts": episode_contexts} if episode_contexts else {}),
                ),
                "interpretation_ids": accepted_ids,
                "experience_ids": experience_ids,
                "development_ids": development_ids,
                "development_status": development_status,
                "motivation_policy": motivation.POLICY,
                "candidate_motives": resolved_motives,
            }
        )
        return complete, changed

    return Prepared(
        instruction,
        payload,
        proposal_draft.DevelopmentDraft if schema is DevelopmentProposal else proposal_draft.Draft,
        identifiers,
        accept,
        cached_pair,
    )
