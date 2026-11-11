"""Project existing verified frame actions; never mine arbitrary private narration."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, or_, select

from backend.core.system_diagnostics import service
from backend.core.text_evidence import EvidenceSpan
from backend.engine.chpm.host_observation_contracts import (
    MAX_SCENE_CHARS,
    ObservedScene,
    ObservedSceneAction,
    scene_view_size,
)
from backend.engine.scene_continuity.ledger import digest, read
from backend.engine.scene_illustrations.snapshots import REGISTRY_KEY, content_hash
from backend.models.chat import ChatMessage


@dataclass(frozen=True)
class Cache:
    input_id: str
    scene_id: str
    views: dict[str, ObservedScene]


async def capture(manager: Any, actors: set[str], targets: set[str]) -> dict[str, ObservedScene]:
    states = manager.state.entity_states or {}
    try:
        ledger = read(states)
    except ValueError:
        return _unavailable("invalid_scene_ledger")
    if not ledger.frame_actions or not isinstance(states.get(REGISTRY_KEY), dict):
        return _unavailable("no_verified_frame")
    message = await _latest(manager)
    if message is None or (
        message.scene_id != manager.state.current_scene_id
        or (message.npc_journal or {}).get("status") == "incomplete"
    ):
        return _unavailable("source_missing_incomplete_or_other_scene")
    if ledger.frame_message_id != message.id or ledger.last_check.get("hash") != digest(
        message.content
    ):
        return _unavailable("source_or_ledger_changed")
    witnesses = _witnesses(states, message)
    minute = ledger.last_check.get("minute")
    minute = minute if type(minute) is int and minute >= 0 else None
    if minute is not None and minute > int(manager.state.in_game_time or 0):
        return _unavailable("future_game_minute")
    actions = [action for row in ledger.frame_actions if (action := _action(row, message, targets))]
    metadata = {
        "source_message_id": message.id,
        "source_revision_id": message.revision_id,
        "source_hash": digest(message.content),
        "scene_id": message.scene_id,
        "recorded_minute": minute,
    }
    result = {}
    for actor in sorted(actors & witnesses):
        view = _bounded(actions, metadata, len(ledger.frame_actions))
        if view is not None:
            result[actor] = view
    service.detail(
        "detail.engine.scene_context.projected",
        source_message_id=message.id,
        eligible_observers=sorted(actors & witnesses),
        projected_observers=sorted(result),
        source_actions=len(ledger.frame_actions),
        visible_actions=len(actions),
    )
    return result


def _unavailable(reason: str) -> dict:
    service.detail("detail.engine.scene_context.unavailable", reason=reason)
    return {}


async def _latest(manager: Any) -> ChatMessage | None:
    request = await manager.db.get(ChatMessage, manager._vn_player_message_id)
    if request is None or request.session_id != manager.game_id or request.role != "user":
        return None
    message: ChatMessage | None = await manager.db.scalar(
        select(ChatMessage)
        .where(
            ChatMessage.session_id == manager.game_id,
            ChatMessage.role == "assistant",
            or_(
                ChatMessage.created_at < request.created_at,
                and_(ChatMessage.created_at == request.created_at, ChatMessage.id < request.id),
            ),
        )
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(1)
    )
    return message


def _witnesses(states: dict, message: ChatMessage) -> set[str]:
    registry = states.get(REGISTRY_KEY)
    snapshots = registry.get("snapshots") if isinstance(registry, dict) else None
    snapshot = snapshots.get(message.id) if isinstance(snapshots, dict) else None
    if not isinstance(snapshot, dict) or (
        snapshot.get("source_message_id") != message.id
        or snapshot.get("source_revision_id") != message.revision_id
        or snapshot.get("scene_id") != message.scene_id
        or snapshot.get("content_hash") != content_hash(message)
    ):
        return set()
    facts = snapshot.get("visible_facts")
    characters = facts.get("characters") if isinstance(facts, dict) else None
    if not isinstance(characters, list):
        return set()
    return {
        row["id"] for row in characters if isinstance(row, dict) and isinstance(row.get("id"), str)
    }


def _action(row: Any, message: ChatMessage, targets: set[str]) -> ObservedSceneAction | None:
    if not set(row.actor_ids).issubset(targets):
        return None
    span = row.evidence_span
    if span is None:
        # A legacy unique quote is recoverable; repeated words need their saved occurrence.
        if message.content.count(row.evidence) != 1:
            return None
        start = message.content.index(row.evidence)
        span = EvidenceSpan(start=start, end=start + len(row.evidence))
    if not span.matches(message.content, row.evidence):
        return None
    return ObservedSceneAction(
        actor_ids=tuple("@player" if value == "__player__" else value for value in row.actor_ids),
        quote=row.evidence,
        evidence_span=span,
    )


def _bounded(
    actions: list[ObservedSceneAction], metadata: dict, total: int
) -> ObservedScene | None:
    selected: list[ObservedSceneAction] = []
    for action in actions:
        proposed = {
            **metadata,
            "meaning": "last_completed_frame_not_ongoing",
            "actions": [row.model_dump(mode="json") for row in [*selected, action]],
            "omitted_actions": total - len(selected) - 1,
        }
        if scene_view_size(proposed) <= MAX_SCENE_CHARS:
            selected.append(action)
    return (
        ObservedScene(**metadata, actions=tuple(selected), omitted_actions=total - len(selected))
        if selected
        else None
    )


def available(manager: Any, actor: str) -> ObservedScene | None:
    cache = getattr(manager, "_chpm_scene_observations", None)
    if not isinstance(cache, Cache) or (cache.input_id, cache.scene_id) != (
        getattr(manager, "_vn_player_message_id", None),
        manager.state.current_scene_id,
    ):
        return None
    return cache.views.get(actor)


def dependencies(source: Any) -> set[str]:
    from backend.engine.chpm import reports

    facts = getattr(source, "facts", None)
    moment = facts.last_observed_scene if facts else None
    return (
        {source.message_id, moment.source_message_id} if moment else {source.message_id}
    ) | reports.dependencies(source)


def matches(moment: ObservedScene, message: Any, session_id: str) -> bool:
    return bool(
        message
        and message.session_id == session_id
        and message.role == "assistant"
        and message.scene_id == moment.scene_id
        and message.revision_id == moment.source_revision_id
        and digest(message.content) == moment.source_hash
        and (getattr(message, "npc_journal", None) or {}).get("status") != "incomplete"
        and all(
            action.evidence_span.matches(message.content, action.quote) for action in moment.actions
        )
    )
