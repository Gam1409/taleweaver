"""One bounded inference per explicit request, outside SQL and session leases."""

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.inference import admission
from backend.core.inference.transport import target
from backend.core.llm_router import GameMasterLLM
from backend.engine.living_world import concordia_adapter, rules, runner
from backend.engine.living_world.decision_context import context_for, fingerprint
from backend.engine.living_world.decisions import INSTRUCTION, Decision, PrivateNotes
from backend.engine.living_world.request_slot import decision_slot
from backend.engine.living_world.schema import Event, Simulation
from backend.engine.living_world.state import save
from backend.models.session_state import SessionState

pending: dict[str, asyncio.Event] = {}


@dataclass(frozen=True)
class Prepared:
    event_id: str
    fence: str
    context: dict[str, Any]
    max_tokens: int
    engine: str
    concurrent: bool = False


def require_enabled(simulation: Simulation, llm: GameMasterLLM) -> None:
    if not simulation.settings.living_world_enabled or not simulation.settings.deliberation_enabled:
        raise HTTPException(409, "Enable Living World private decisions first.")
    if not admission.enabled() or target(llm) is None:
        raise HTTPException(
            409,
            "Private decisions require inference serialization and an Ollama or OpenAI-compatible utility model.",
        )
    if simulation.settings.decision_engine == "concordia" and not concordia_adapter.available():
        raise HTTPException(409, "Install the concordia extra on Python 3.12 or 3.13 first.")
    if simulation.deliberation_attempts >= simulation.settings.max_deliberations:
        raise HTTPException(409, "The timeline's decision request budget is exhausted.")


async def prepare(
    db: AsyncSession, state: SessionState, simulation: Simulation, llm: GameMasterLLM
) -> Prepared:
    require_enabled(simulation, llm)
    limit = simulation.target
    if simulation.settings.mode == "PAUSE":
        limit = min(limit, int(state.in_game_time or 0))
    event = runner.next_event(simulation, limit)
    if event is None or event.kind not in {"DECISION", "SOCIAL"}:
        raise HTTPException(
            409,
            "Continue catch-up to the next DECISION or SOCIAL event first.",
        )
    if event.attempts >= 2 or not runner.dependencies_ready(simulation, event):
        raise HTTPException(
            409, "The decision exhausted its attempts or has unfinished prerequisites."
        )
    if event.actor not in simulation.private_notes and len(simulation.private_notes) >= 128:
        raise HTTPException(409, "The private NPC memory capacity is full.")
    context = await context_for(db, state, simulation, event)
    event.attempts += 1
    event.status = "WAITING_FOR_LLM"
    simulation.status = "WAITING_FOR_LLM"
    simulation.deliberation_attempts += 1
    save(state, simulation)
    await db.commit()
    await db.refresh(state)
    prepared = Prepared(
        event.event_id,
        fingerprint(state, context),
        context,
        simulation.settings.decision_max_tokens,
        simulation.settings.decision_engine,
        simulation.settings.allow_concurrent_requests,
    )
    # Release even the read transaction before queue admission or remote inference.
    await db.rollback()
    return prepared


async def infer(llm: GameMasterLLM, prepared: Prepared, game_id: str) -> Decision:
    llm.max_tokens = min(llm.max_tokens, prepared.max_tokens)
    llm.enable_thinking = False
    async with decision_slot(prepared.concurrent):
        result = await llm.aexecute_simple_task(
            INSTRUCTION,
            json.dumps(prepared.context, ensure_ascii=False),
            llm.model,
            game_id=game_id,
            operation="living_world_decision",
        )
    return Decision.model_validate_json(result)


async def infer_until_stopped(
    llm: GameMasterLLM, prepared: Prepared, game_id: str, stop: asyncio.Event
) -> Decision:
    async def generate() -> Decision:
        return await infer(llm, prepared, game_id)

    request = (
        concordia_adapter.decide(prepared.context, generate)
        if prepared.engine == "concordia"
        else generate()
    )
    task = asyncio.create_task(request)
    stopped = asyncio.create_task(stop.wait())
    try:
        done, _ = await asyncio.wait(
            {task, stopped}, timeout=float(llm.request_timeout), return_when=asyncio.FIRST_COMPLETED
        )
        if stop.is_set():
            raise HTTPException(409, "The private decision was stopped. No result was applied.")
        if task not in done:
            raise HTTPException(
                504,
                "The utility model deadline expired. Check the inference queue before retrying.",
            )
        return task.result()
    finally:
        task.cancel()
        stopped.cancel()
        task.add_done_callback(_consume_late_result)
        await asyncio.gather(stopped, return_exceptions=True)


async def apply(
    db: AsyncSession,
    state: SessionState,
    simulation: Simulation,
    prepared: Prepared,
    decision: Decision,
) -> None:
    event = next((item for item in simulation.events if item.event_id == prepared.event_id), None)
    if event is None:
        raise HTTPException(409, "The decision timeline changed. The late result was discarded.")
    context = await context_for(db, state, simulation, event)
    check_stop(state.session_id)
    if fingerprint(state, context) != prepared.fence:
        raise HTTPException(
            409, "The world changed during inference. The late result was discarded."
        )
    if decision.action == "MOVE" and decision.destination not in context["destinations"]:
        raise HTTPException(
            422, "The model proposed an unavailable destination. No result was applied."
        )
    if decision.action == "WAIT" and decision.destination:
        raise HTTPException(422, "A waiting decision cannot specify a destination.")
    if decision.action == "TALK":
        await apply_speech(db, state, simulation, event, prepared, decision)
        return
    if (
        decision.speech
        or decision.participant
        or (event.kind == "SOCIAL" and decision.action == "MOVE")
    ):
        raise HTTPException(422, "The decision does not match this event type.")
    proposal = Event(
        event_id=event.event_id,
        due=event.due,
        kind=decision.action,
        actor=event.actor,
        destination=decision.destination,
    )
    await rules.apply(db, state, proposal)
    if proposal.status == "CANCELLED":
        raise HTTPException(409, "The proposed action is no longer permitted.")
    check_stop(state.session_id)
    simulation.private_notes[event.actor] = PrivateNotes(
        goal=decision.goal,
        belief=decision.belief,
        observations=context["observations"],
    )
    # Retain the concrete committed action so later observations can use it.
    event.kind = proposal.kind
    event.destination = proposal.destination
    event.result = proposal.result[:300]
    simulation.private_notes[event.actor].observations = [
        *simulation.private_notes[event.actor].observations,
        event.result,
    ][-8:]
    event.status = "COMMITTED"
    event.committed_at = max(simulation.cursor, event.due)
    simulation.cursor = event.committed_at
    simulation.status = "PARTIAL"
    simulation.last_run_events = 1
    state.in_game_time = max(int(state.in_game_time or 0), simulation.cursor)
    save(state, simulation)
    await db.commit()


async def apply_speech(
    db: AsyncSession,
    state: SessionState,
    simulation: Simulation,
    event: Event,
    prepared: Prepared,
    decision: Decision,
) -> None:
    permitted = {item["id"] for item in prepared.context["participants"]}
    if decision.participant not in permitted or not decision.speech.strip() or decision.destination:
        raise HTTPException(422, "Speech requires a social event and a present participant.")
    event.participant = decision.participant
    proposal = event.model_copy(update={"kind": "MEET"})
    await rules.apply(db, state, proposal)
    if proposal.status == "CANCELLED":
        raise HTTPException(409, "The participants can no longer talk.")
    check_stop(state.session_id)
    simulation.private_notes[event.actor] = PrivateNotes(
        goal=decision.goal,
        belief=decision.belief,
        observations=prepared.context["observations"],
    )
    event.kind = "SOCIAL"
    event.speech = decision.speech
    event.result = f'{event.actor[:40]} said to {event.participant[:40]}: "{decision.speech}"'
    simulation.private_notes[event.actor].observations = [
        *simulation.private_notes[event.actor].observations,
        event.result,
    ][-8:]
    event.status = "COMMITTED"
    event.committed_at = max(simulation.cursor, event.due)
    simulation.cursor = event.committed_at
    simulation.status = "PARTIAL"
    simulation.last_run_events = 1
    state.in_game_time = max(int(state.in_game_time or 0), simulation.cursor)
    save(state, simulation)
    await db.commit()


def _consume_late_result(task: asyncio.Task) -> None:
    if not task.cancelled():
        task.exception()


def check_stop(game_id: str) -> None:
    stop = pending.get(game_id)
    if stop is not None and stop.is_set():
        raise HTTPException(409, "The private decision was stopped. No result was applied.")
