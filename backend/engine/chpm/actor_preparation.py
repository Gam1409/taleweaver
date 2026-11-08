"""Prepare observer inputs sequentially; cognitive jobs never touch the database."""

from dataclasses import dataclass
from typing import Any

from backend.engine.chpm import (
    agenda,
    causal_memory,
    cognition,
    context,
    continuation,
    host_adapter,
    memory,
    performance,
)
from backend.engine.chpm.host_state import Mind, removed_messages
from backend.engine.chpm.schema import Decision, Observation


@dataclass
class PreparedActor:
    actor_id: str
    observed: Observation
    supplied: dict
    previous: Decision | None
    mind: Mind | None


async def prepare(manager: Any, turn: Any, actor: Any, observed: Observation) -> PreparedActor:
    previous = continuation.previous(turn.initial, actor.id)
    retained = await memory.recall(
        manager,
        actor.id,
        turn.initial.memories.get(actor.id, []),
        turn.initial.settings.memory_limit,
    )
    entries = await agenda.recall(manager, actor.id, turn.initial.agenda)
    invalid: set[str] = set()
    authored = actor
    if turn.initial.settings.mode == "live":
        turn.minds[actor.id] = await host_adapter.prepare(manager, turn, actor, observed)
        continuation.rebase_gap(turn, actor.id)
        authored = host_adapter.actor_view(actor, turn.minds[actor.id])
        if actor.id in turn.initial.minds:
            invalid = removed_messages(turn.initial.minds[actor.id], turn.minds[actor.id])
    retained = [entry for entry in retained if entry.source_message_id not in invalid]
    for message_id in sorted(invalid):
        entries = agenda.retract(entries, message_id)
    causal_memory.invalidate(turn, actor.id, invalid)
    turn.memories[actor.id] = retained
    turn.agendas[actor.id] = entries
    legacy = (
        previous if not invalid and not retained and turn.initial.settings.memory_limit else None
    )
    supplied = await context.actor_context(manager, authored, legacy, retained)
    if actor.id in turn.minds:
        host_adapter.add_context(supplied, turn.minds[actor.id])
    supplied["declared_agenda_not_world_facts"] = agenda.context(turn.agendas[actor.id])
    supplied["causal_continuity_not_world_facts"] = causal_memory.view(
        turn.causal_threads.get(actor.id, []), turn.minds.get(actor.id)
    )
    supplied["agenda_creation_available"] = (
        len(turn.initial.agenda) < agenda.MAX_RECORDS
        and len(supplied["declared_agenda_not_world_facts"]) < agenda.MAX_ACTIVE
    )
    if turn.initial.recovery.pending_gap_turns:
        supplied["continuity_gap"] = continuation.gap_context(turn.initial)
    supplied["_chpm_gap_cursors"] = turn.gap_cursors
    perceived = turn.perceptions[actor.id]
    actor_observation = observed.model_copy(
        update={
            "player_request": "\n".join(perceived.quotes),
            "perception_uncertain": perceived.uncertain,
            "perception_kinds": perceived.quote_kinds,
        }
    )
    supplied["observation"] = actor_observation.model_dump()
    return PreparedActor(actor.id, actor_observation, supplied, previous, turn.minds.get(actor.id))


async def run(manager: Any, turn: Any, job: PreparedActor) -> tuple[Decision, Mind | None]:
    token = performance.actor_id.set(job.actor_id)
    try:
        return await _run(manager, turn, job)
    finally:
        performance.actor_id.reset(token)


async def _run(manager: Any, turn: Any, job: PreparedActor) -> tuple[Decision, Mind | None]:
    if job.mind is not None:
        decision, mind = await cognition.deliberate(
            manager,
            turn.initial.settings,
            turn.usage,
            job.actor_id,
            job.observed,
            job.supplied,
            turn.agendas[job.actor_id],
            job.mind,
            job.previous,
        )
    else:
        decision = await cognition.decide(
            manager,
            turn.initial.settings,
            turn.usage,
            job.actor_id,
            job.observed,
            job.supplied,
            turn.agendas[job.actor_id],
            job.previous,
        )
        mind = None
    decision.perception_audit = turn.perceptions[job.actor_id].coverage
    return decision, mind


def apply(turn: Any, actor: str, result: tuple[Decision, Mind | None]) -> None:
    decision, mind = result
    turn.decisions[actor] = decision
    if mind is not None:
        turn.minds[actor] = mind
