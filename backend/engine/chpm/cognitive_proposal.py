"""Prepare the same complete cognitive context and acceptance boundary for either workflow."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.engine import turn_controls
from backend.engine.chpm import (
    agenda,
    agent_context,
    appraisal,
    development,
    development_request,
    experience,
    json_contract,
    motivation,
    prompts,
    proposal_references,
    quote_references,
    semantic_choice,
    semantic_recall,
)
from backend.engine.chpm.agent_tools import Tools
from backend.engine.chpm.appraisal_contracts import INSTRUCTIONS
from backend.engine.chpm.development_contracts import DevelopmentProposal
from backend.engine.chpm.errors import StaleControlError
from backend.engine.chpm.host_state import Mind
from backend.engine.chpm.kernel import existing, fingerprint
from backend.engine.chpm.notebook_tools import NotebookDraft
from backend.engine.chpm.schema import AgendaEntry, Decision, Observation, Settings


@dataclass(frozen=True)
class Prepared:
    instruction: str
    payload: dict
    schema: type[proposal_references.ReferenceDraft]
    identifiers: dict
    accept: Callable[[proposal_references.ReferenceDraft], tuple[Decision, Mind]]
    references: quote_references.References
    control: dict
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
            **(
                {"pending_actions_not_world_facts": tools.actions.context()}
                if tools.actions
                else {}
            ),
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
    control = turn_controls.operation(
        turn_controls.scope(manager, "proposal", observation=observation),
        "submit_decision",
        actor_id=actor_id,
    ).model_dump(exclude_none=True)
    instruction = (
        prompts.proposal(command_owned=tools is not None and tools.actions is not None)
        + INSTRUCTIONS
        + motivation.INSTRUCTIONS
        + experience.INSTRUCTIONS
        + semantic_choice.INSTRUCTIONS
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
        reference_binding=control,
    )
    references = quote_references.build(
        window,
        motives,
        development_sources,
        binding={
            "observation": observation.model_dump(exclude={"player_request"}),
            "control": control,
        },
    )
    # Wire selectors and attempt bindings do not change the semantic decision input.
    semantic_payload = {
        **{
            name: value
            for name, value in payload.items()
            if name not in {"reference_scope", "request_control"}
        },
        "appraisal_context": window.payload,
    }
    key = fingerprint(semantic_payload)
    cached = existing(previous, observation, key)
    cached_pair = (cached, mind) if cached is not None else None

    def accept(draft: proposal_references.ReferenceDraft) -> tuple[Decision, Mind]:
        if not turn_controls.bind_current(manager, control, "proposal", observation=observation):
            raise StaleControlError(
                "CHPM proposal belongs to an inactive or different turn attempt."
            )
        json_contract.validate_identifiers(type(draft), draft.model_dump(mode="json"), identifiers)
        raw = draft.materialize(motives, references, entries)
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
        if tools is not None and tools.actions is not None:
            tools.actions.approved = True
        return complete, changed

    return Prepared(
        instruction,
        payload,
        proposal_references.ReferenceDevelopmentDraft
        if schema is DevelopmentProposal
        else proposal_references.ReferenceDraft,
        identifiers,
        accept,
        references,
        control,
        cached_pair,
    )
