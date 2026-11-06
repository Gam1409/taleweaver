"""Observer-scoped inputs: no player journal, global RAG, or other NPC's thoughts."""

from datetime import timezone
from typing import Any

from backend.engine.chpm.kernel import ChpmError, digest
from backend.engine.chpm.schema import Decision, MemoryEntry, Observation
from backend.engine.chpm.state import load
from backend.engine.npc_presence import physically_present
from backend.engine.personality.profile import personality_context
from backend.models.chat import ChatMessage


def available(actor: Any, state: Any) -> bool:
    override = (state.entity_states or {}).get(actor.id) or {}
    return (
        getattr(actor, "entity_type", "") == "NPC"
        and override.get("current_scene_id", actor.current_scene_id) == state.current_scene_id
        and not override.get("is_hidden", getattr(actor, "is_hidden", False))
        and not override.get("is_defeated", getattr(actor, "is_defeated", False))
        and physically_present(actor, state)
    )


async def observation(manager: Any, _request: str) -> Observation:
    source = await manager.db.get(ChatMessage, manager._vn_player_message_id)
    if source is None or source.session_id != manager.game_id or source.role != "user":
        raise ChpmError("CHPM requires a saved player input in this session.")
    created = source.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    current = load(manager.state)
    # The session lease serializes completed CHPM revisions. Preserve the same
    # order on an exact retry; new inputs do not depend on timestamp/UUID ties.
    previous = next(
        (
            item.observation
            for item in current.actors.values()
            if item.observation.message_id == source.id
        ),
        None,
    )
    return Observation(
        session_id=manager.game_id,
        message_id=source.id,
        revision_id=source.revision_id,
        content_hash=digest(source.content),
        sequence=int(created.timestamp() * 1_000_000),
        turn_revision=previous.turn_revision if previous else current.revision + 1,
        scene_id=manager.state.current_scene_id,
        source_scene_id=source.scene_id,
        minute=max(0, int(manager.state.in_game_time or 0)),
        player_request=source.content,
    )


async def actor_context(
    manager: Any,
    actor: Any,
    previous: Decision | None,
    memories: list[MemoryEntry] | None = None,
) -> dict:
    speech = ""
    if previous and previous.status == "delivered" and previous.reply_id:
        reply = await manager.db.get(ChatMessage, previous.reply_id)
        if (
            reply is not None
            and reply.session_id == manager.game_id
            and reply.role == "assistant"
            and reply.revision_id == previous.reply_revision
            and digest(reply.content) == previous.reply_hash
        ):
            speech = previous.spoken_evidence
    return {
        "actor_id": actor.id,
        "name": str(actor.name),
        "authored_character": str(getattr(actor, "character", "") or ""),
        "authored_goal": str(getattr(actor, "goal", "") or ""),
        "personality": personality_context(actor),
        "own_previous_words": speech,
        "witnessed_utterances_not_world_facts": [entry.model_dump() for entry in memories or []],
    }
