"""Bound deep cognition while retaining every selected character's private state."""

from backend.engine.chpm.errors import RecoverableChpmError
from backend.engine.chpm.schema import KernelState, Perception, Settings


def active_limit(settings: Settings, present: int | None = None) -> int:
    count = len(settings.actor_ids) if present is None else present
    return min(count, settings.max_active_npcs)


def recent(state: KernelState, present: set[str]) -> list[str]:
    eligible = {
        actor: revision
        for actor, revision in state.last_active.items()
        if not state.recovery.last_gap_revision or revision > state.recovery.last_gap_revision
    }
    latest = max(eligible.values(), default=-1)
    return sorted(actor for actor in present if eligible.get(actor) == latest)


def select(state: KernelState, perceptions: dict[str, Perception]) -> list[str]:
    available = sorted(perceptions)
    limit = active_limit(state.settings, len(available))
    engaged = [actor for actor in available if perceptions[actor].engaged]
    if len(engaged) > limit:
        raise RecoverableChpmError(
            f"This turn directly involves {len(engaged)} NPCs, above the active limit of {limit}. "
            "Raise Active NPCs per turn and its request budget, or split the interaction. "
            "No directly involved character was silently omitted."
        )
    if len(available) <= limit:
        return available
    if engaged:
        return engaged
    ongoing = recent(state, set(available))
    if ongoing:
        return ongoing[:limit]
    # Oldest completed participation first; stable ties are independent of host list order.
    waiting = sorted(available, key=lambda actor: (state.last_active.get(actor, -1), actor))
    return waiting[:limit]


def instruction(deferred: dict[str, str]) -> str:
    if not deferred:
        return ""
    import json

    return (
        "\nINACTIVE CHPM CHARACTERS: These present characters retain their saved state but "
        "received no decision this turn. Do not invent new dialogue, decisions, agreement, "
        "goals, personality changes or private thoughts for them. They may remain present "
        "without a narrated reaction. If the scene needs their decision, it needs a new "
        "controlled turn. The reviewer must reject violations of this boundary. These "
        "restrictions concern visible story prose and CHPM updates; an independently enabled "
        "private portrait footer follows its own output contract.\n"
        + json.dumps(deferred, ensure_ascii=False)
    )
