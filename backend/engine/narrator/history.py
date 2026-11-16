"""Read current completed prose from an already loaded, session-owned history window."""

from collections.abc import Sequence
from typing import Any

from backend.engine.debug_transcript import field, without_debug


def completed_narrations(rows: Sequence[Any], session_id: str) -> list[str]:
    result = []
    for message in without_debug(list(rows)):
        if field(message, "session_id") != session_id or field(message, "role") != "assistant":
            continue
        task = field(message, "npc_journal")
        if isinstance(task, dict) and task.get("status") == "incomplete":
            continue
        content = field(message, "content")
        if isinstance(content, str) and content.strip():
            result.append(content)
    return result
