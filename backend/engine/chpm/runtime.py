"""Turn-local preparation; accepted decisions are persisted with the completed reply."""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from backend.core.engine_detailed_trace import step
from backend.core.game_modes import is_vn
from backend.engine.chpm import (
    agenda,
    agent_context,
    agent_views,
    capacity,
    causal_memory,
    context,
    continuation,
    development_context,
    host_adapter,
    host_observations,
    memory,
    narrative_context,
    passages,
    perception,
    prompts,
    roster,
    semantic_recall,
)
from backend.engine.chpm.causal_contracts import Thread
from backend.engine.chpm.core import relationships
from backend.engine.chpm.core.reducer import TransitionError
from backend.engine.chpm.errors import RecoverableChpmError
from backend.engine.chpm.host_state import Mind
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
from backend.engine.npc_presentation.runtime import defer_characters
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
    deferred_names: dict[str, str] = field(default_factory=dict)
    reply_character_budget: int | None = None
    agent_clothing: dict[str, dict] = field(default_factory=dict)
    simplified: bool = False
    fallback_identities: dict = field(default_factory=dict)
    fallback_issues: list[str] = field(default_factory=list)
    simplified_text: str | None = None
    player_request: str = ""
    gap_cursors: dict[str, int] = field(default_factory=dict)
    causal_threads: dict[str, list[Thread]] = field(default_factory=dict)
    reconciled_minds: dict[str, Mind] = field(default_factory=dict)
    semantic_hits: dict[str, list[semantic_recall.Hit]] = field(default_factory=dict)
    scene_cues: dict[str, str] = field(default_factory=dict)


def current(manager: Any) -> Turn | None:
    value = getattr(manager, "_chpm_turn", None)
    return value if isinstance(value, Turn) else None


def public_status(state: Any) -> dict:
    return continuation.snapshot_status(state)


def buffered(manager: Any) -> bool:
    turn = current(manager)
    return bool(
        turn and turn.initial.settings.mode == "live" and (turn.decisions or turn.simplified)
    )


def contract_data(turn: Turn) -> dict:
    data = {
        actor: {
            "name": turn.names.get(actor, actor),
            **decision.selected.model_dump(),
            "ongoing_agenda_not_world_facts": agenda.narrator_context(
                turn.agendas.get(actor, []), actor
            ),
            "causal_continuity_not_world_facts": causal_memory.view(
                turn.causal_threads.get(actor, []), turn.minds.get(actor)
            ),
        }
        for actor, decision in turn.decisions.items()
    }
    for actor, mind in turn.minds.items():
        if actor in data:
            decision = turn.decisions[actor]
            data[actor]["agent_observed_sources"] = agent_context.present(decision, mind)
            data[actor]["authored_identity"] = host_adapter.narrative_identity(mind)
            scene = host_observations.situation(mind)
            if scene:
                data[actor]["current_scene_observations"] = scene
            if decision.choice_preference is not None:
                data[actor]["choice_preference_not_prose"] = decision.choice_preference.model_dump()
                data[actor]["previous_intention_not_world_completion"] = (
                    decision.previous_intention.model_dump()
                    if decision.previous_intention
                    else None
                )
            data[actor]["subjective_experience_not_traits"] = narrative_context.experience_reasons(
                mind, continuation.experience_view(mind, turn.gap_cursors)
            )
            if turn.initial.recovery.pending_gap_turns:
                data[actor]["continuity_gap"] = continuation.gap_context(turn.initial)
            data[actor]["developing_tendencies"] = development_context.tendencies(mind)
            changed = [
                b
                for b in mind.snapshot.beliefs
                if set(b.interpretation_ids) & set(turn.decisions[actor].interpretation_ids)
            ]
            data[actor]["subjective_assessments_not_world_facts"] = relationships.claims(
                mind.snapshot, tuple(changed)
            )
            data[actor]["selected_motives_not_world_facts"] = narrative_context.compact_motives(
                decision, data[actor]
            )
    return data


def contract(turn: Turn) -> str:
    if turn.simplified:
        return continuation.contract(turn)
    return (
        prompts.NARRATE
        + json.dumps(contract_data(turn), ensure_ascii=False, separators=(",", ":"))
        + roster.instruction(turn.deferred_names)
        + (
            f"\nKeep the complete reply within {turn.reply_character_budget} characters for review."
            if turn.reply_character_budget
            else ""
        )
    )


@step("npc.prepare")
async def prepare(manager: Any, message: str, actors: list[Any]) -> str:
    state = load(manager.state)
    if state.settings.mode == "off" or not is_vn(manager.adventure):
        return ""
    input_id = getattr(manager, "_vn_player_message_id", None)
    if not input_id:
        return ""
    old = current(manager)
    if old is not None and old.input_id == input_id:
        if not old.simplified:
            defer_characters(manager, set(old.usage.actor_failures))
        return contract(old) if buffered(manager) else ""
    turn = Turn(
        state, input_id, player_request=message, gap_cursors=dict(state.recovery.gap_cursors)
    )
    manager._chpm_turn = turn
    selected = [
        actor
        for actor in actors
        if actor.id in state.settings.actor_ids and context.available(actor, manager.state)
    ]
    if not selected:
        return ""
    from backend.engine.chpm import host_scene

    await host_scene.prepare(manager, turn, selected)
    turn.fallback_identities = await continuation.recalled_identities(manager, state, selected)
    await causal_memory.prepare(manager, turn, {actor.id for actor in selected})
    manager._chpm_publish_after_commit = state.settings.mode == "live"
    turn.present_names = {
        actor.id: str(actor.name) for actor in actors if context.available(actor, manager.state)
    }
    if continuation.enabled(turn) and state.recovery.cooldown_remaining:
        continuation.activate(turn, "cooldown")
        return contract(turn)
    try:
        if len(selected) <= state.settings.max_active_npcs:
            await capacity.admit(manager, state, [actor.id for actor in selected])
        else:
            capacity.ensure_budget(
                state,
                [actor.id for actor in selected[: state.settings.max_active_npcs]],
            )
        started = time.perf_counter()
        try:
            await _prepare(manager, turn, message, selected)
        finally:
            turn.usage.preparation_ms = (time.perf_counter() - started) * 1000
    except Exception as exc:
        _preparation_failed(manager, turn, exc)
    if turn.usage.status != "failed":
        turn.usage.status = "prepared" if state.settings.mode == "live" else "shadow"
        defer_characters(manager, set(turn.usage.actor_failures))
    manager._chpm_publish_after_commit = buffered(manager)
    return contract(turn) if buffered(manager) else ""


def _preparation_failed(manager: Any, turn: Turn, exc: Exception) -> None:
    turn.usage.status = "failed"
    turn.usage.detail = (
        str(exc) if isinstance(exc, (ChpmError, TransitionError)) else type(exc).__name__
    )
    logger.warning(
        "CHPM preparation failed: session=%s error=%s", manager.game_id, type(exc).__name__
    )
    if isinstance(exc, RecoverableChpmError) and continuation.enabled(turn):
        continuation.activate(turn, "analysis_failed", error=exc)
    elif turn.initial.settings.mode == "live":
        raise ChpmError("CHPM could not prepare this turn. " + turn.usage.detail) from exc
    else:
        turn.decisions = {}


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
            manager,
            turn.initial.settings,
            turn.usage,
            observed.player_request,
            turn.names,
            recent_interlocutors=roster.recent(turn.initial, set(turn.names)),
        )
    active_ids = roster.select(turn.initial, turn.perceptions)
    active = [actor for actor in actors if actor.id in active_ids]
    turn.deferred_names = {
        actor.id: str(actor.name) for actor in actors if actor.id not in active_ids
    }
    turn.names = {actor.id: str(actor.name) for actor in active}
    await capacity.admit(manager, turn.initial, active_ids)
    turn.usage.detail = (
        f"Active NPCs: {len(active)}; present but inactive: {len(turn.deferred_names)}."
    )
    if turn.initial.settings.mode == "live" and turn.initial.settings.agent_steps:
        turn.agent_clothing = await agent_views.capture(manager)
    await semantic_recall.prepare(manager, turn, active_ids, observed)
    from backend.engine.chpm import parallel

    await parallel.prepare(manager, turn, active, observed, _prepare_actor)
    from backend.engine.chpm.rendering import preflight

    preflight(turn)


async def _prepare_actor(manager: Any, turn: Turn, actor: Any, observed: Observation) -> None:
    from backend.engine.chpm import actor_preparation

    job = await actor_preparation.prepare(manager, turn, actor, observed)
    await release_for_model(manager)
    result = await actor_preparation.run(manager, turn, job)
    actor_preparation.apply(turn, actor.id, result)


def finish(manager: Any, reply: Any, *, completed: bool) -> None:
    turn = current(manager)
    if turn is None:
        return
    if turn.simplified:
        continuation.finish(manager, turn, reply)
        manager._chpm_turn = None
        return
    if not completed:
        return
    if turn.minds and reply.session_id != manager.game_id:
        raise ChpmError("CHPM completed reply belongs to another session.")
    result = turn.initial.model_copy(deep=True)
    result.usage = turn.usage
    for actor, decision in turn.decisions.items():
        _finish_decision(turn, decision, reply)
        result.actors[actor] = decision
        result.last_active[actor] = turn.initial.revision + 1
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
        causal_memory.apply(turn, result, reply, passages.index(reply.content))
        result.recovery.gap_cursors = turn.gap_cursors
        continuation.mark_verified(result)
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
