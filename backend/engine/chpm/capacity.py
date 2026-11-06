"""Visible pre-turn admission instead of partial work or silent history eviction."""

from typing import Any

from backend.engine.chpm import host_sources, roster
from backend.engine.chpm.core.history import count
from backend.engine.chpm.core.limits import MAX_BELIEFS, MAX_EVENTS, MAX_EXPERIENCES
from backend.engine.chpm.errors import RecoverableChpmError
from backend.engine.chpm.host_state import Mind
from backend.engine.chpm.schema import KernelState, Settings

# One frame, one world change, up to 32 excerpts, two interpretations, two experiences, own speech,
# up to twelve heard passages, four tool observations and two developmental reflections. A single
# observer may receive all heard entries even in a twenty-character scene.
EVENT_RESERVE = 57
SOURCE_RESERVE = 51
BELIEF_RESERVE = 3
EXPERIENCE_RESERVE = 2


def required_calls(settings: Settings, count: int | None = None) -> int:
    if settings.mode == "off":
        return 0
    actors = roster.active_limit(settings) if count is None else count
    # Perception + proposals; live also needs review and a repair/review pair.
    return actors * (1 + (settings.agent_steps if settings.mode == "live" else 0)) + (
        5 if settings.mode == "live" else 1
    )


def inspect(mind: Mind) -> dict:
    used = {
        "events": count(mind.snapshot),
        "evidence": len(mind.snapshot.evidence),
        "sources": len(mind.sources),
        "beliefs": len(mind.snapshot.beliefs),
        "experiences": len(mind.snapshot.experiences),
    }
    limits = {
        "events": MAX_EVENTS,
        "evidence": MAX_EVENTS,
        "sources": MAX_EVENTS,
        "beliefs": MAX_BELIEFS,
        "experiences": MAX_EXPERIENCES,
    }
    reserve = {
        "events": EVENT_RESERVE,
        "evidence": EVENT_RESERVE,
        "sources": SOURCE_RESERVE,
        "beliefs": BELIEF_RESERVE,
        "experiences": EXPERIENCE_RESERVE,
    }
    remaining = {key: limits[key] - size for key, size in used.items()}
    blocked = [key for key, free in remaining.items() if free < reserve[key]]
    warning = any(size >= limits[key] * 0.8 for key, size in used.items())
    return {
        "status": "pause_required" if blocked else "warning" if warning else "ready",
        "used": used,
        "limits": limits,
        "turn_reserve": reserve,
        "blocking_resources": blocked,
        "active_events": len(mind.snapshot.journal),
        "archived_events": count(mind.snapshot) - len(mind.snapshot.journal),
        "archive_blocks": len(mind.snapshot.archive),
    }


def ensure_budget(state: KernelState, actors: list[str]) -> None:
    required = required_calls(state.settings, len(actors))
    if state.settings.max_calls_per_turn < required:
        raise RecoverableChpmError(
            f"CHPM is paused before model requests: this turn needs a budget of at least {required} "
            "requests, including perception and (in live mode) one shared proposal retry, "
            "one narration repair, repeat review and configured agent lookups. "
            "Increase Requests per turn in session NPC behavior settings. No history was changed."
        )


def ensure_turn(state: KernelState, actors: list[str]) -> None:
    ensure_budget(state, actors)
    if state.settings.mode != "live":
        return
    full = [
        actor
        for actor in actors
        if actor in state.minds and inspect(state.minds[actor])["status"] == "pause_required"
    ]
    if full:
        raise RecoverableChpmError(
            "CHPM is paused before model requests: psychological history has insufficient space "
            "for a complete turn for " + ", ".join(full) + ". "
            "No history was discarded or replaced. Open session NPC behavior settings and "
            "explicitly choose Standard, or deselect these NPCs, to continue without their CHPM "
            "control. Their original identity and psychological history remain saved. "
            "The exact archive has a finite storage limit; no archived sources were discarded."
        )


async def admit(manager: Any, state: KernelState, actors: list[str]) -> None:
    ensure_budget(state, actors)
    if state.settings.mode != "live":
        return
    # Source edits/deletions may have freed a causal suffix. Do not let a stale
    # full projection prevent the usual reconciliation from ever running.
    candidate = state.model_copy(update={"minds": dict(state.minds)})
    for actor in actors:
        mind = state.minds.get(actor)
        if mind and inspect(mind)["status"] == "pause_required":
            candidate.minds[actor] = await host_sources.reconcile(manager, mind)
    ensure_turn(candidate, actors)
