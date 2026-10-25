"""VN time is completed elapsed time, not an RPG surcharge on every message."""

from typing import Any

MAX_ELAPSED_MINUTES = 1440


def _bounded_duration(minutes: int, adventure: Any) -> int:
    cap = getattr(adventure, "max_time_per_turn", None)
    if cap is None:
        config = getattr(adventure, "time_config", None) or {}
        cap = config.get("max_time_per_turn") if isinstance(config, dict) else None
    try:
        cap = int(cap) if cap is not None else None
    except (ValueError, TypeError):
        cap = None
    limit = min(MAX_ELAPSED_MINUTES, cap) if cap and cap > 0 else MAX_ELAPSED_MINUTES
    return max(0, min(int(minutes), limit))


def apply_elapsed_time(state: Any, event: Any, adventure: Any) -> bool:
    """Keep the existing wire key, but interpret it as total elapsed time for VN.

    Short exchanges may take zero whole minutes. Explicit waits and sustained
    activity advance the clock even if neither the scene nor sequence changes.
    """
    before = state.in_game_time
    if event.time_override_minutes is not None:
        state.in_game_time = max(0, int(event.time_override_minutes))
    else:
        elapsed = _bounded_duration(event.extra_time_minutes, adventure)
        # Narration must see the actual allowed duration, including configured caps.
        event.extra_time_minutes = elapsed
        state.in_game_time = max(0, int(before) + elapsed)
    return state.in_game_time != before


def boundary_elapsed_time(adventure: Any, event: Any = None) -> int:
    """Scene changes use a default duration only when no explicit time was applied."""
    if event is not None and (
        event.time_override_minutes is not None or event.extra_time_minutes > 0
    ):
        return 0
    default = getattr(adventure, "time_per_turn", None)
    return _bounded_duration(5 if default is None else default, adventure)
