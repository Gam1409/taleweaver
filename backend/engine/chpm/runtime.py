"""Turn-local preparation; accepted decisions are persisted with the completed reply."""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from backend.core.diagnostic_failures import failure_details, failure_reason
from backend.core.engine_detailed_trace import step
from backend.core.game_modes import is_vn
from backend.core.state_rejection_trace import reject
from backend.engine import turn_controls
from backend.engine.chpm import (
    agenda,
    agent_context,
    agent_views,
    capacity,
    causal_memory,
    context,
    continuation,
    control_settings,
    development_context,
    host_adapter,
    host_observations,
    memory,
    narrative_context,
    observable_state,
    passages,
    perception,
    prompts,
    roster,
    semantic_recall,
)
from backend.engine.chpm.causal_contracts import Thread
from backend.engine.chpm.core import relationships
from backend.engine.chpm.core.reducer import TransitionError
from backend.engine.chpm.delivery import finish_decision as _finish_decision
from backend.engine.chpm.delivery import new_memories as _new_memories
from backend.engine.chpm.errors import RecoverableChpmError
from backend.engine.chpm.host_state import Mind
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.notebook_tools import NotebookDraft
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
from backend.engine.chpm.state import KEY, load, save
from backend.engine.npc_actions import acknowledgment as command_acknowledgment
from backend.engine.npc_actions import execution_frame as owner_frame
from backend.engine.npc_actions import feedback as command_feedback
from backend.engine.npc_actions import source_control
from backend.engine.npc_actions.control import model_outcomes
from backend.engine.npc_actions.preview import Draft as ActionDraft
from backend.engine.turn_replay.transactions import release_for_model

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from backend.engine.npc_actions.custody_citations import Proof as CustodyProof


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
    notebook_drafts: dict[str, NotebookDraft] = field(default_factory=dict)
    agendas: dict[str, list[AgendaEntry]] = field(default_factory=dict)
    minds: dict[str, Mind] = field(default_factory=dict)
    deferred_names: dict[str, str] = field(default_factory=dict)
    reply_character_budget: int | None = None
    agent_clothing: dict[str, dict] = field(default_factory=dict)
    observable_views: dict[str, observable_state.View] = field(default_factory=dict)
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
    catchup: Any = None
    report_origins: dict = field(default_factory=dict)
    report_origins_enabled: bool = True
    catchup_unavailable: list = field(default_factory=list)
    action_drafts: dict[str, ActionDraft] = field(default_factory=dict)
    action_outcomes: dict[str, list[dict]] = field(default_factory=dict)
    publication_feedback: dict[str, dict] = field(default_factory=dict)
    control: dict = field(default_factory=dict)
    host_rejections: list[dict] = field(default_factory=list)
    review_operation: dict = field(default_factory=dict)
    review_change_feedback: dict = field(default_factory=dict)
    reviewed_custody: "CustodyProof | None" = None
    execution_frame: owner_frame.Frame | None = None


def current(manager: Any) -> Turn | None:
    value = getattr(manager, "_chpm_turn", None)
    if not isinstance(value, Turn):
        return None
    if value.control and not turn_controls.bind_current(manager, value.control):
        return None
    return value


def public_status(state: Any) -> dict:
    return continuation.snapshot_status(state)


def buffered(manager: Any) -> bool:
    turn = current(manager)
    return bool(
        turn and turn.initial.settings.mode == "live" and (turn.decisions or turn.simplified)
    )


def contract_data(turn: Turn) -> dict:
    outcomes = model_outcomes(turn)
    data = {
        actor: {
            "name": turn.names.get(actor, actor),
            **owner_frame.intention(actor, decision, outcomes),
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
                key = (
                    "observations_before_command_publication"
                    if actor in outcomes
                    else "current_scene_observations"
                )
                data[actor][key] = scene
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
    for actor, records in outcomes.items():
        if actor in data:
            data[actor]["authoritative_command_outcomes"] = owner_frame.records(turn, records)
            data[actor]["observation_time"] = (
                "before_command_publication, including host resolution"
            )
    for actor, records in command_feedback.project(turn).items():
        if actor in data:
            data[actor]["rejected_command_previews"] = records
    data.update(owner_frame.context(turn))
    return data


def contract(turn: Turn) -> str:
    if turn.simplified:
        return continuation.contract(turn)
    from backend.engine.npc_actions.instructions import for_outcomes

    return (
        prompts.narration(command_owned=bool(turn.action_outcomes))
        + for_outcomes(turn.action_outcomes)
        + command_feedback.instructions(turn)
        + json.dumps(contract_data(turn), ensure_ascii=False, separators=(",", ":"))
        + roster.instruction(turn.deferred_names)
        + (
            f"\nKeep the complete reply within {turn.reply_character_budget} characters for review."
            if turn.reply_character_budget
            else ""
        )
    )


@step("npc.prepare")
async def prepare(
    manager: Any, message: str, actors: list[Any], *, host_rejections: list[dict] | None = None
) -> str:
    settings = control_settings.read((manager.state.entity_states or {}).get(KEY))
    if (
        settings.mode == "off"
        or settings.control_scope != "dialogue"
        or not is_vn(manager.adventure)
    ):
        return ""
    from backend.engine.chpm.template_settings import ensure_session_compatible

    try:
        ensure_session_compatible(manager.state, settings)
    except ValueError as exc:
        raise ChpmError(str(exc)) from exc
    state = load(manager.state)
    input_id = getattr(manager, "_vn_player_message_id", None)
    if not input_id:
        return ""
    old = current(manager)
    if old is not None and old.input_id == input_id:
        return contract(old) if buffered(manager) else ""
    turn = Turn(
        state,
        input_id,
        player_request=message,
        gap_cursors=dict(state.recovery.gap_cursors),
        control=turn_controls.scope(manager, "npc_preparation"),
        host_rejections=list(host_rejections or ()),
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
    manager._chpm_publish_after_commit = buffered(manager)
    return contract(turn) if buffered(manager) else ""


def _preparation_failed(manager: Any, turn: Turn, exc: Exception) -> None:
    from backend.engine.npc_actions.postconditions import PostconditionViolationError

    if isinstance(exc, PostconditionViolationError):
        # Publication already traced this operation. Keep other actors' minds out of that trace.
        raise exc
    reject(
        "emotion",
        "chpm.preparation_failed",
        failure_reason(exc, "CHPM preparation failed before an update could be confirmed."),
        session_id=manager.game_id,
        input_id=turn.input_id,
        decisions=turn.decisions,
        minds=turn.minds,
        perceptions=turn.perceptions,
        usage=turn.usage,
        confirmed_state=turn.initial,
        error_type=type(exc).__name__,
        **failure_details(exc),
    )
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
        from backend.engine.chpm import recovery_queue

        turn.catchup = await recovery_queue.prepare(manager, turn)
        await release_for_model(manager)
        turn.perceptions = await perception.project(
            manager,
            turn.initial.settings,
            turn.usage,
            observed.player_request,
            turn.names,
            recent_interlocutors=roster.recent(turn.initial, set(turn.names)),
            **({"catchup": turn.catchup} if turn.catchup is not None else {}),
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
        turn.observable_views = await observable_state.capture(manager, active_ids, observed)
        if turn.initial.settings.action_tools:
            from backend.engine.npc_actions.preparation import capture

            turn.action_drafts = await capture(manager, turn.observable_views, observed)
    await semantic_recall.prepare(manager, turn, active_ids, observed)
    from backend.engine.chpm import parallel

    await parallel.prepare(manager, turn, active, observed, _prepare_actor)
    await command_acknowledgment.ensure_current(manager, turn)
    from backend.engine.chpm.rendering import preflight

    if not turn_controls.bind_current(manager, turn.control, observation=observed):
        raise turn_controls.ControlBindingError(
            "The NPC preparation belongs to an inactive attempt."
        )
    turn.control = turn_controls.scope(manager, "narration_review", observation=observed)
    preflight(turn)
    if turn.action_drafts:
        from backend.engine.npc_actions.runtime import publish_turn

        await publish_turn(manager, turn)
        if not turn_controls.bind_current(manager, turn.control, observation=observed):
            raise turn_controls.ControlBindingError(
                "The NPC publication belongs to an inactive attempt."
            )
        turn.control = turn_controls.scope(manager, "narration_review", observation=observed)
        await owner_frame.capture(manager, turn, observed)
        preflight(turn)


async def _prepare_actor(manager: Any, turn: Turn, actor: Any, observed: Observation) -> None:
    from backend.engine.chpm import actor_preparation

    job = await actor_preparation.prepare(manager, turn, actor, observed)
    await release_for_model(manager)
    result = await actor_preparation.run(manager, turn, job)
    actor_preparation.apply(turn, actor.id, result, notebook=job.notebook)


def finish(manager: Any, reply: Any, *, completed: bool) -> None:
    turn = current(manager)
    if turn is None:
        return
    if turn.simplified:
        continuation.finish(manager, turn, reply)
        if completed:
            source_control.stamp(manager, turn, reply)
        manager._chpm_turn = None
        return
    if not completed:
        if turn.decisions or turn.minds:
            reject(
                "emotion",
                "chpm.commit_unconfirmed",
                "The narrator reply is incomplete.",
                session_id=manager.game_id,
                decisions=turn.decisions,
                minds=turn.minds,
                verdict=turn.verdict,
                confirmed_state=turn.initial,
            )
        return
    if turn.minds and reply.session_id != manager.game_id:
        reject(
            "emotion",
            "chpm.reply_scope_mismatch",
            "CHPM completed reply belongs to another session.",
            decisions=turn.decisions,
            expected_session_id=manager.game_id,
            reply_session_id=reply.session_id,
        )
        raise ChpmError("CHPM completed reply belongs to another session.")
    result = turn.initial.model_copy(deep=True)
    result.usage = turn.usage
    from backend.engine.chpm import movement_feedback

    outcomes = movement_feedback.read(manager.state, reply)
    for actor, decision in turn.decisions.items():
        _finish_decision(turn, decision, reply)
        decision.last_publication = command_acknowledgment.capture(turn, decision)
        result.actors[actor] = decision
        result.last_active[actor] = turn.initial.revision + 1
        result.memories[actor] = turn.memories.get(actor, [])
        additions = movement_feedback.qualify(outcomes, reply, _new_memories(turn, decision, reply))
        memory.append(result, actor, additions)
        if actor in turn.minds:
            result.minds[actor] = host_adapter.finish(
                turn, reply, additions, actor, minute=max(0, int(manager.state.in_game_time or 0))
            )
    if turn.initial.settings.mode == "live" and turn.verdict:
        retained_agenda = [entry for entry in result.agenda if entry.actor_id not in turn.agendas]
        retained_agenda.extend(entry for entries in turn.agendas.values() for entry in entries)
        result.agenda = agenda.apply(retained_agenda, turn.decisions, turn.verdict, reply)
        causal_memory.apply(
            turn, result, reply, passages.index(reply.content), movement_outcomes=outcomes
        )
        result.recovery.gap_cursors = turn.gap_cursors
        continuation.mark_verified(result)
    save(manager.state, result, expected_revision=turn.initial.revision)
    source_control.stamp(manager, turn, reply)
    manager._chpm_turn = None
