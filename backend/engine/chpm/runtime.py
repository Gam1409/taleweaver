"""Turn-local preparation; accepted decisions are persisted with the completed reply."""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from backend.core.game_modes import is_vn
from backend.engine.chpm import (
    agenda,
    cognition,
    context,
    host_adapter,
    memory,
    perception,
    prompts,
)
from backend.engine.chpm.core.reducer import TransitionError
from backend.engine.chpm.host_state import Mind, removed_messages
from backend.engine.chpm.kernel import ChpmError, digest
from backend.engine.chpm.schema import (
    AgendaEntry,
    Decision,
    KernelState,
    MemoryEntry,
    Observation,
    Perception,
    Usage,
    Verdict,
)
from backend.engine.chpm.state import load, save
from backend.engine.turn_replay.transactions import release_for_model

logger = logging.getLogger(__name__)


@dataclass
class Turn:
    initial: KernelState
    input_id: str
    decisions: dict[str, Decision] = field(default_factory=dict)
    usage: Usage = field(default_factory=Usage)
    verdict: Verdict | None = None
    names: dict[str, str] = field(default_factory=dict)
    present_names: dict[str, str] = field(default_factory=dict)
    perceptions: dict[str, Perception] = field(default_factory=dict)
    memories: dict[str, list[MemoryEntry]] = field(default_factory=dict)
    agendas: dict[str, list[AgendaEntry]] = field(default_factory=dict)
    minds: dict[str, Mind] = field(default_factory=dict)


def current(manager: Any) -> Turn | None:
    value = getattr(manager, "_chpm_turn", None)
    return value if isinstance(value, Turn) else None


def buffered(manager: Any) -> bool:
    turn = current(manager)
    return bool(turn and turn.initial.settings.mode == "live" and turn.decisions)


def contract(turn: Turn) -> str:
    data = {
        actor: {"name": turn.names.get(actor, actor), **decision.selected.model_dump()}
        for actor, decision in turn.decisions.items()
    }
    for actor, mind in turn.minds.items():
        if actor in data:
            data[actor]["authored_identity"] = host_adapter.narrative_identity(mind)
    return prompts.NARRATE + json.dumps(data, ensure_ascii=False)


async def prepare(manager: Any, message: str, actors: list[Any]) -> str:
    state = load(manager.state)
    if state.settings.mode == "off" or not is_vn(manager.adventure):
        return ""
    input_id = getattr(manager, "_vn_player_message_id", None)
    if not input_id:
        return ""
    old = current(manager)
    if old is not None and old.input_id == input_id:
        return contract(old) if buffered(manager) else ""
    turn = Turn(state, input_id)
    manager._chpm_turn = turn
    selected = [
        actor
        for actor in actors
        if actor.id in state.settings.actor_ids and context.available(actor, manager.state)
    ]
    if not selected:
        return ""
    turn.present_names = {
        actor.id: str(actor.name) for actor in actors if context.available(actor, manager.state)
    }
    try:
        await _prepare(manager, turn, message, selected)
    except Exception as exc:
        turn.usage.status = "failed"
        turn.usage.detail = (
            str(exc) if isinstance(exc, (ChpmError, TransitionError)) else type(exc).__name__
        )
        logger.warning(
            "CHPM preparation failed: session=%s error=%s", manager.game_id, type(exc).__name__
        )
        if state.settings.mode == "live":
            raise ChpmError("CHPM could not prepare this turn. " + turn.usage.detail) from exc
        turn.decisions = {}
        return ""
    turn.usage.status = "prepared" if state.settings.mode == "live" else "shadow"
    manager._chpm_publish_after_commit = buffered(manager)
    return contract(turn) if buffered(manager) else ""


async def _prepare(manager: Any, turn: Turn, message: str, actors: list[Any]) -> None:
    if not (
        getattr(manager, "_turn_replay_recorded", False) or getattr(manager, "_replaying", False)
    ):
        raise ChpmError("CHPM needs a recoverable turn snapshot.")
    observed = await context.observation(manager, message)
    await release_for_model(manager)
    turn.names = {actor.id: str(actor.name) for actor in actors}
    if observed.source_scene_id and observed.source_scene_id != observed.scene_id:
        turn.perceptions = {
            actor.id: Perception(actor_id=actor.id, uncertain=True) for actor in actors
        }
    else:
        turn.perceptions = await perception.project(
            manager, turn.initial.settings, turn.usage, observed.player_request, turn.names
        )
    for actor in sorted(actors, key=lambda item: item.id):
        await _prepare_actor(manager, turn, actor, observed)


async def _prepare_actor(manager: Any, turn: Turn, actor: Any, observed: Observation) -> None:
    previous = turn.initial.actors.get(actor.id)
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
        authored = host_adapter.actor_view(actor, turn.minds[actor.id])
        if actor.id in turn.initial.minds:
            invalid = removed_messages(turn.initial.minds[actor.id], turn.minds[actor.id])
    retained = [entry for entry in retained if entry.source_message_id not in invalid]
    for message_id in sorted(invalid):
        entries = agenda.retract(entries, message_id)
    turn.memories[actor.id] = retained
    turn.agendas[actor.id] = entries
    legacy = (
        previous if not invalid and not retained and turn.initial.settings.memory_limit else None
    )
    supplied = await context.actor_context(manager, authored, legacy, retained)
    if actor.id in turn.minds:
        supplied["psychological_state"] = host_adapter.context(turn.minds[actor.id])
    supplied["declared_agenda_not_world_facts"] = agenda.context(turn.agendas[actor.id])
    supplied["agenda_creation_available"] = (
        len(turn.initial.agenda) < agenda.MAX_RECORDS
        and len(supplied["declared_agenda_not_world_facts"]) < agenda.MAX_ACTIVE
    )
    perceived = turn.perceptions[actor.id]
    actor_observation = observed.model_copy(
        update={
            "player_request": "\n".join(perceived.quotes),
            "perception_uncertain": perceived.uncertain,
        }
    )
    supplied["observation"] = actor_observation.model_dump()
    # Recall and core-source reconciliation opened a read transaction after the
    # initial release. The session lease protects the snapshot while inference runs.
    await release_for_model(manager)
    turn.decisions[actor.id] = await cognition.decide(
        manager,
        turn.initial.settings,
        turn.usage,
        actor.id,
        actor_observation,
        supplied,
        turn.agendas[actor.id],
        previous,
    )


def finish(manager: Any, reply: Any, *, completed: bool) -> None:
    turn = current(manager)
    if turn is None or not completed:
        return
    if turn.minds and reply.session_id != manager.game_id:
        raise ChpmError("CHPM completed reply belongs to another session.")
    result = turn.initial.model_copy(deep=True)
    result.usage = turn.usage
    for actor, decision in turn.decisions.items():
        _finish_decision(turn, decision, reply)
        result.actors[actor] = decision
        result.memories[actor] = turn.memories.get(actor, [])
        additions = _new_memories(turn, decision, reply)
        memory.append(result, actor, additions)
        if actor in turn.minds:
            result.minds[actor] = host_adapter.finish(
                turn, reply, additions, actor, minute=max(0, int(manager.state.in_game_time or 0))
            )
    if turn.initial.settings.mode == "live" and turn.verdict:
        retained_agenda = [entry for entry in result.agenda if entry.actor_id not in turn.agendas]
        retained_agenda.extend(entry for entries in turn.agendas.values() for entry in entries)
        result.agenda = agenda.apply(retained_agenda, turn.decisions, turn.verdict, reply)
    save(manager.state, result, expected_revision=turn.initial.revision)
    manager._chpm_turn = None


def _finish_decision(turn: Turn, decision: Decision, reply: Any) -> None:
    if turn.initial.settings.mode == "shadow":
        decision.status = "shadow"
        return
    if turn.verdict is None or not turn.verdict.matches:
        raise ChpmError("CHPM cannot commit a reply without successful validation.")
    decision.status = "delivered"
    decision.reply_id = reply.id
    decision.reply_revision = reply.revision_id
    decision.reply_hash = digest(reply.content)
    decision.spoken_evidence = next(
        evidence.quote
        for evidence in turn.verdict.evidence
        if evidence.actor_id == decision.actor_id
    )


def _new_memories(turn: Turn, decision: Decision, reply: Any) -> list[MemoryEntry]:
    actor = decision.actor_id
    source = decision.observation
    perceived = turn.perceptions.get(actor, Perception(actor_id=actor))
    additions = [
        MemoryEntry(
            source_message_id=source.message_id,
            source_revision_id=source.revision_id,
            source_hash=source.content_hash,
            source_role="user",
            scene_id=source.source_scene_id or source.scene_id,
            observer_id=actor,
            speaker_id="@player",
            kind="player_observation",
            quote=quote,
        )
        for quote in perceived.quotes
    ]
    if turn.verdict is None:
        return additions
    if decision.spoken_evidence:
        additions.append(
            memory.from_source(reply, actor, actor, decision.spoken_evidence, "own_speech")
        )
    additions.extend(
        memory.from_source(reply, actor, heard.speaker_id, heard.quote, "heard_speech")
        for heard in turn.verdict.heard
        if heard.actor_id == actor
    )
    return additions
