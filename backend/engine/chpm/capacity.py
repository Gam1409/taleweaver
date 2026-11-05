"""Visible pre-turn admission instead of partial work or silent history eviction."""

from typing import Any

from backend.engine.chpm import host_sources
from backend.engine.chpm.core.limits import MAX_BELIEFS, MAX_EVENTS
from backend.engine.chpm.host_state import Mind
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.schema import KernelState, Settings

# One frame, up to three perceived excerpts, two interpretations, own speech,
# and up to twelve heard passages. A single observer may receive all heard entries.
EVENT_RESERVE = 19
SOURCE_RESERVE = 17
BELIEF_RESERVE = 2


def required_calls(settings: Settings, count: int | None = None) -> int:
    if settings.mode == "off":
        return 0
    actors = len(settings.actor_ids) if count is None else count
    # Perception + proposals; live also needs review and a repair/review pair.
    return actors + (4 if settings.mode == "live" else 1)


def inspect(mind: Mind) -> dict:
    used = {
        "events": len(mind.snapshot.journal),
        "evidence": len(mind.snapshot.evidence),
        "sources": len(mind.sources),
        "beliefs": len(mind.snapshot.beliefs),
    }
    limits = {
        "events": MAX_EVENTS,
        "evidence": MAX_EVENTS,
        "sources": MAX_EVENTS,
        "beliefs": MAX_BELIEFS,
    }
    reserve = {
        "events": EVENT_RESERVE,
        "evidence": EVENT_RESERVE,
        "sources": SOURCE_RESERVE,
        "beliefs": BELIEF_RESERVE,
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
    }


def _ensure_budget(state: KernelState, actors: list[str]) -> None:
    required = required_calls(state.settings, len(actors))
    if state.settings.max_calls_per_turn < required:
        raise ChpmError(
            f"CHPM is paused before model requests: this turn needs a budget of at least {required} "
            "requests, including perception and (in live mode) one repair and repeat review. "
            "Increase Requests per turn in session NPC behavior settings. No history was changed."
        )


def ensure_turn(state: KernelState, actors: list[str]) -> None:
    _ensure_budget(state, actors)
    if state.settings.mode != "live":
        return
    full = [
        actor
        for actor in actors
        if actor in state.minds and inspect(state.minds[actor])["status"] == "pause_required"
    ]
    if full:
        raise ChpmError(
            "CHPM is paused before model requests: psychological history has insufficient space "
            "for a complete turn for " + ", ".join(full) + ". "
            "No history was discarded or replaced. Open session NPC behavior settings and "
            "explicitly choose Standard, or deselect these NPCs, to continue without their CHPM "
            "control. Their original identity and psychological history remain saved. "
            "Automatic archive/consolidation is not yet available."
        )


async def admit(manager: Any, state: KernelState, actors: list[str]) -> None:
    _ensure_budget(state, actors)
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
