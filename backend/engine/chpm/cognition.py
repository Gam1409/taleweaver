"""Shared proposal/selection boundary for session turns and isolated evaluations."""

from typing import Any

from backend.engine.chpm import agenda, inference, prompts
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
