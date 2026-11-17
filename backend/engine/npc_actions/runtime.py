"""The host coordinates command publication after all cognitive jobs have completed."""

from hashlib import sha256
from typing import Any

from sqlalchemy import select

from backend.engine.chpm import control_settings
from backend.engine.chpm.state import KEY
from backend.engine.npc_actions.publication import publish
from backend.models.chat import ChatMessage


async def publish_turn(manager: Any, turn: Any) -> None:
    if not turn.action_drafts or turn.simplified:
        return
    settings = control_settings.read((manager.state.entity_states or {}).get(KEY))
    enabled = (
        settings.mode == "live"
        and settings.action_tools
        and settings.workflow == "integrated"
        and settings == turn.initial.settings
    )
    for actor in sorted(turn.decisions):
        if actor in turn.action_outcomes or actor not in turn.action_drafts:
            continue
        draft = turn.action_drafts[actor]
        if not draft.approved or not draft.requests:
            continue
        valid = enabled and await _current_input(manager, turn.decisions[actor].observation)
        turn.action_outcomes[actor] = (
            await publish(manager, draft)
            if valid
            else [
                {
                    "index": index,
                    "tool": request.tool,
                    "status": "stale",
                    "message": "The controlling settings or input changed before publication.",
                }
                for index, request in enumerate(draft.requests)
            ]
        )


async def _current_input(manager: Any, observation: Any) -> bool:
    if (
        manager.game_id != observation.session_id
        or getattr(manager, "_vn_player_message_id", None) != observation.message_id
    ):
        return False
    row = await manager.db.scalar(
        select(ChatMessage).where(
            ChatMessage.id == observation.message_id,
            ChatMessage.session_id == manager.game_id,
            ChatMessage.role == "user",
        )
    )
    return (
        row is not None
        and row.revision_id == observation.revision_id
        and sha256(row.content.encode()).hexdigest() == observation.content_hash
    )
