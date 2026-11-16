"""Connect deterministic chapter completion to the canonical session finalizer."""

from typing import Any

from backend.core.game_modes import is_vn

FINAL_SEQUENCE_NOTE = "Congratulations! You have completed the final sequence."


def sequence_end_in_progress(manager: Any) -> bool:
    return manager.state.active_sequence_id in getattr(manager, "_ending_sequence_ids", ())


async def execute_sequence_end_script(manager: Any, code: str, target_id: str) -> list[str]:
    """Prevent same-chapter callbacks only while its existing end script executes."""
    previous: frozenset[str | None] = getattr(manager, "_ending_sequence_ids", frozenset())
    manager._ending_sequence_ids = previous | {manager.state.active_sequence_id}
    try:
        messages: list[str] = await manager._execute_inline_script(
            code, "on_end_sequence", target_id
        )
        return messages
    finally:
        manager._ending_sequence_ids = previous


def session_is_terminal(state: Any) -> bool:
    """Turn managers load this canonical relationship during initialization."""
    return getattr(getattr(state, "session", None), "status", None) in {"completed", "game_over"}


async def finalize_completed_sequence(manager: Any) -> None:
    """Finalize a completed marker once, without reconstructing or granting rewards."""
    if (
        is_vn(manager.adventure)
        or not manager.state.is_completed
        or session_is_terminal(manager.state)
    ):
        return
    await manager._finalize_session("completed", FINAL_SEQUENCE_NOTE)
