"""Content-free live phases supplement durable queue state in the player interface."""

import time
from typing import Literal

from backend.core.llm_diagnostics import emit

Phase = Literal["preparing", "extracting", "waiting_to_save", "saving"]
_active: dict[str, tuple[str, Phase, float]] = {}


def set_phase(session_id: str, message_id: str, phase: Phase) -> None:
    _active[session_id] = (message_id, phase, time.monotonic())
    emit("npc.learning.phase", session_id=session_id, message_id=message_id, phase=phase)


def finish(session_id: str, message_id: str) -> None:
    current = _active.get(session_id)
    if current and current[0] == message_id:
        _active.pop(session_id, None)


def snapshot(session_id: str, tasks: list[dict]) -> dict:
    active = _active.get(session_id)
    if active:
        return {"phase": active[1], "elapsed_seconds": int(time.monotonic() - active[2])}
    statuses = [task.get("status") for task in tasks if isinstance(task, dict)]
    if "running" in statuses:
        return {"phase": "recovering", "elapsed_seconds": 0}
    if "pending" in statuses:
        return {"phase": "queued", "elapsed_seconds": 0}
    if "failed" in statuses:
        return {"phase": "retry_pending", "elapsed_seconds": 0}
    return {"phase": "up_to_date", "elapsed_seconds": 0}
