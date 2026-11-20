"""The host coordinates command publication after all cognitive jobs have completed."""

from hashlib import sha256
from typing import Any

from sqlalchemy import select

from backend.engine import turn_controls
from backend.engine.chpm import control_settings
from backend.engine.chpm.state import KEY
from backend.engine.npc_actions.publication import publish, rejected_results
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
        if not draft.approved:
            continue
        valid = enabled and await _current_input(manager, turn.decisions[actor].observation)
        if not draft.requests and not (valid and _current_empty_plan(manager, turn, actor)):
            continue
        if not valid:
            turn.action_outcomes[actor] = rejected_results(draft, "stale")
        elif settings.npc_decision_mode == "two_phase" and settings.control_scope == "dialogue":
            turn.action_outcomes[actor] = await publish(manager, draft, verify_postconditions=True)
        else:
            turn.action_outcomes[actor] = await publish(manager, draft)


def _current_empty_plan(manager: Any, turn: Any, actor: str) -> bool:
    """An empty final list cannot borrow control from another captured plan."""
    if control_settings.read((manager.state.entity_states or {}).get(KEY)) != turn.initial.settings:
        return False
    scope = turn.action_drafts[actor].scope
    if scope.scene_id != manager.state.current_scene_id:
        return False
    observation = turn.decisions[actor].observation
    return (
        scope.session_id,
        scope.actor_id,
        scope.input_id,
        scope.input_revision,
        scope.input_hash,
        scope.scene_id,
    ) == (
        observation.session_id,
        actor,
        observation.message_id,
        observation.revision_id,
        observation.content_hash,
        observation.scene_id,
    ) and turn_controls.bind_current(
        manager, scope.control, "npc_command_preview", observation=observation
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
