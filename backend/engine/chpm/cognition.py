"""Shared proposal/selection boundary for session turns and isolated evaluations."""

from typing import Any

from backend.engine.chpm import (
    agenda,
    agent,
    belief_recall,
    causal_memory,
    cognitive_proposal,
    inference,
    integrated_request,
    prompts,
    proposal_attempt,
    semantic_choice,
    semantic_recall,
)
from backend.engine.chpm.agent_tools import Tools
from backend.engine.chpm.host_state import Mind
from backend.engine.chpm.kernel import ChpmError, existing, fingerprint, select
from backend.engine.chpm.notebook_tools import NotebookDraft
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
    usage.workflow = "staged"
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
    *,
    notebook: NotebookDraft | None = None,
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
    turn = getattr(manager, "_chpm_turn", None)
    pinned = causal_memory.pins(mind, getattr(turn, "causal_threads", {}).get(actor_id, []))
    hits = getattr(turn, "semantic_hits", {}).get(actor_id, [])
    pinned = semantic_recall.merge(mind, pinned, hits)
    episode_contexts = semantic_recall.contexts(pinned, hits)
    if episode_contexts:
        supplied["retrieved_episode_context"] = {
            alias: episode_contexts[key].model_dump(exclude_none=True)
            for alias, (key, _, _) in pinned.items()
            if key in episode_contexts
        }
    integrated = (
        settings.workflow == "integrated" and settings.mode == "live" and bool(settings.agent_steps)
    )
    usage.workflow = "integrated" if integrated else "staged"
    pinned_beliefs = {}
    audit: list[dict] = []
    if settings.agent_steps and settings.mode == "live" and not integrated:
        tools, audit = await agent.investigate(
            manager,
            settings,
            usage,
            mind,
            observation,
            supplied,
            **({"pinned": pinned} if pinned else {}),
            notebook=notebook,
        )
        mind, pinned = tools.mind, tools.pins
        episode_contexts = semantic_recall.contexts(pinned, hits)
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
            **({"private_notebook_not_world_facts": notebook.context()} if notebook else {}),
        }
    if episode_contexts:
        supplied["retrieved_episode_context"] = {
            alias: episode_contexts[key].model_dump(exclude_none=True)
            for alias, (key, _, _) in pinned.items()
            if key in episode_contexts
        }

    def prepare(tools: Tools | None = None) -> cognitive_proposal.Prepared:
        return cognitive_proposal.prepare(
            manager,
            settings,
            actor_id,
            observation,
            supplied,
            entries,
            mind,
            previous,
            pinned=pinned,
            pinned_beliefs=pinned_beliefs,
            focus=focus,
            hits=hits,
            audit=audit,
            notebook=notebook,
            tools=tools,
        )

    if integrated:
        tools = agent.make_tools(manager, mind, observation, pinned=pinned, notebook=notebook)
        return await integrated_request.request(manager, settings, usage, tools, audit, prepare)
    prepared = prepare()
    if prepared.cached is not None:
        return prepared.cached
    return await proposal_attempt.request(
        manager,
        settings,
        usage,
        prepared.instruction,
        prepared.payload,
        prepared.schema,
        prepared.identifiers,
        prepared.accept,
    )
