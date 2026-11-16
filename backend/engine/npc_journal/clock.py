"""Carry the source reply's recording clock, never a later worker's current time."""

from typing import Any


def clock_fields(value: Any) -> dict[str, int]:
    minute = value.get("game_minute") if isinstance(value, dict) else None
    return {"game_minute": minute} if type(minute) is int and minute >= 0 else {}
