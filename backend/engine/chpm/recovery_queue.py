"""Read bounded historical sources; only a reviewed current turn commits catch-up."""

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import and_, or_, select, update

from backend.core.system_diagnostics import service
from backend.core.text_passages import Passage, spans
from backend.engine.chpm.kernel import digest
from backend.engine.chpm.recovery_contracts import RECOVERY_FRAGMENTS as MAX_FRAGMENTS
from backend.engine.chpm.recovery_contracts import RecoveryAudit
from backend.models.chat import ChatMessage


@dataclass
class Batch:
    message: Any
    audit: RecoveryAudit
    available: dict[str, Passage]
    offsets: dict[str, int]
    original: dict | None = None
    accepted: dict[str, list[Any]] = field(default_factory=dict)
    checked: set[str] = field(default_factory=set)
    error: str = ""
    uncertain: dict[str, list[Any]] = field(default_factory=dict)


def stamp(manager: Any, turn: Any, reply: Any) -> None:
    if not turn.fallback_identities:
        return
    audit = RecoveryAudit(
        content_hash=digest(reply.content),
        revision_id=reply.revision_id,
        scene_id=getattr(reply, "scene_id", None) or "",
        game_minute=max(0, int(getattr(manager.state, "in_game_time", 0) or 0)),
        actors={actor: 0 for actor in turn.fallback_identities},
        speakers=dict(list(sorted(turn.present_names.items()))[:128]),
    )
    reply.npc_recovery = audit.model_dump()


async def prepare(manager: Any, turn: Any) -> Batch | None:
    turn.catchup_unavailable = []
    if turn.initial.settings.mode != "live" or not turn.initial.recovery.total_simplified_turns:
        return None
    request = await manager.db.get(ChatMessage, turn.input_id)
    if request is None or request.session_id != manager.game_id:
        return None
    eligible = [ChatMessage.npc_recovery["actors"][actor].as_integer() >= 0 for actor in turn.names]
    if not eligible:
        return None
    # Completed sources are excluded by removing that actor's cursor, not by deleting history.
    rows = await manager.db.scalars(
        select(ChatMessage)
        .where(
            ChatMessage.session_id == manager.game_id,
            ChatMessage.role == "assistant",
            or_(*eligible),
            or_(
                ChatMessage.created_at < request.created_at,
                and_(ChatMessage.created_at == request.created_at, ChatMessage.id < request.id),
            ),
        )
        .order_by(ChatMessage.created_at, ChatMessage.id)
        .limit(4)
        .execution_options(populate_existing=True)
    )
    for row in rows:
        batch = _batch(row, turn.names)
        if batch is not None:
            return batch
        turn.catchup_unavailable.append((row.id, deepcopy(row.npc_recovery)))
    return await _legacy(manager, turn)


async def _legacy(manager: Any, turn: Any) -> Batch | None:
    """Only the retained old diagnostic window proves an older NPC's eligibility."""
    for record in turn.initial.recovery.recent:
        eligible = set(record.actor_ids) & set(turn.names)
        if not eligible:
            continue
        row = await manager.db.get(ChatMessage, record.reply_id)
        if (
            row is None
            or row.npc_recovery is not None
            or row.session_id != manager.game_id
            or row.role != "assistant"
        ):
            continue
        if (digest(row.content), row.revision_id) != (record.reply_hash, record.reply_revision):
            continue
        audit = RecoveryAudit(
            content_hash=record.reply_hash,
            revision_id=row.revision_id,
            scene_id=row.scene_id or "",
            game_minute=(row.npc_journal or {}).get("game_minute"),
            actors={actor: 0 for actor in record.actor_ids},
            speakers={actor: turn.names.get(actor, actor) for actor in record.actor_ids},
        )
        return _batch_view(row, audit, turn.names)
    return None


def _batch(message: Any, names: dict) -> Batch | None:
    try:
        audit = RecoveryAudit.model_validate(message.npc_recovery)
    except ValueError:
        service.detail(
            "detail.engine.npc.catchup_unavailable",
            source_message_id=message.id,
            reason="invalid_audit",
        )
        return None
    if (audit.content_hash, audit.revision_id, audit.scene_id) != (
        digest(message.content),
        message.revision_id,
        message.scene_id or "",
    ):
        service.detail(
            "detail.engine.npc.catchup_unavailable",
            source_message_id=message.id,
            reason="source_changed",
        )
        return None
    if (message.npc_journal or {}).get("status") == "incomplete":
        return None
    return _batch_view(message, audit, names)


def _batch_view(message: Any, audit: RecoveryAudit, names: dict) -> Batch | None:
    passages = list(spans(message.content).values())
    offsets = {
        actor: offset
        for actor, offset in audit.actors.items()
        if actor in names and offset < len(passages)
    }
    if not offsets:
        return None
    start = min(offsets.values())
    available = {
        f"h{index}": passage
        for index, passage in enumerate(passages[start : start + MAX_FRAGMENTS], start)
    }
    # NPCs already farther along must never have their cursor moved backwards.
    offsets = {actor: offset for actor, offset in offsets.items() if offset < start + MAX_FRAGMENTS}
    return Batch(
        message, audit, available, offsets, deepcopy(getattr(message, "npc_recovery", None))
    )


def payload(batch: Batch) -> dict:
    return {
        "source_message_id": batch.message.id,
        "scene_id": batch.audit.scene_id,
        "recorded_game_minute": batch.audit.game_minute,
        "eligible_observers": sorted(batch.offsets),
        "eligible_observers_by_fragment": {
            key: sorted(actor for actor, cursor in batch.offsets.items() if int(key[1:]) >= cursor)
            for key in batch.available
        },
        "present_speakers_at_source": batch.audit.speakers,
        "fragments": {key: value.text for key, value in batch.available.items()},
    }


async def commit(manager: Any, turn: Any) -> None:
    if getattr(turn, "simplified", False):
        return
    batch = getattr(turn, "catchup", None)
    unavailable = getattr(turn, "catchup_unavailable", [])
    if not unavailable and (batch is None or not batch.checked):
        return
    if turn.verdict is None or not turn.verdict.matches:
        raise ValueError("NPC catch-up requires the shared successful narration review.")
    await _retire_unavailable(manager, unavailable)
    if batch is None or not batch.checked:
        return
    row = await manager.db.get(ChatMessage, batch.message.id, populate_existing=True)
    if (
        row is None
        or row.npc_recovery != batch.original
        or digest(row.content) != batch.audit.content_hash
        or row.revision_id != batch.audit.revision_id
        or (row.scene_id or "") != batch.audit.scene_id
    ):
        raise ValueError("NPC catch-up source changed before reviewed commit.")
    changed = batch.audit.model_copy(deep=True)
    end = max(int(key[1:]) for key in batch.available) + 1
    count = len(spans(row.content))
    for actor in batch.checked & set(turn.decisions):
        previous = changed.uncertain_fragments.get(actor, [])
        changed.uncertain_fragments[actor] = list(
            dict.fromkeys([*previous, *batch.uncertain.get(actor, [])])
        )
        if end >= count:
            changed.actors.pop(actor, None)
        else:
            changed.actors[actor] = end
    row.npc_recovery = changed.model_dump()
    service.detail(
        "detail.engine.npc.catchup_committed",
        source_message_id=row.id,
        actors=sorted(batch.checked & set(turn.decisions)),
        fragments=len(batch.available),
        uncertain_fragments=sum(map(len, changed.uncertain_fragments.values())),
    )


async def _retire_unavailable(manager: Any, candidates: list) -> None:
    for identifier, original in candidates:
        row = await manager.db.get(ChatMessage, identifier, populate_existing=True)
        if row is None or row.npc_recovery != original or not isinstance(original, dict):
            continue
        actors = original.get("actors")
        row.npc_recovery = {
            **original,
            "actors": {},
            "unavailable_reason": "Historical proof is missing, changed or invalid; not admitted.",
            "unavailable_actors": list(actors)[:20] if isinstance(actors, dict) else [],
        }
        service.detail(
            "detail.engine.npc.catchup_source_retained_for_review", source_message_id=row.id
        )


async def capture(db: Any, session_id: str) -> dict:
    rows = await db.execute(
        select(ChatMessage.id, ChatMessage.npc_recovery).where(
            ChatMessage.session_id == session_id, ChatMessage.npc_recovery.is_not(None)
        )
    )
    return {key: deepcopy(value) for key, value in rows if isinstance(value, dict)}


async def restore(db: Any, session_id: str, snapshot: dict) -> None:
    await db.execute(
        update(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .values(npc_recovery=None)
        .execution_options(synchronize_session=False)
    )
    for key, value in snapshot.items():
        await db.execute(
            update(ChatMessage)
            .where(ChatMessage.session_id == session_id, ChatMessage.id == key)
            .values(npc_recovery=deepcopy(value))
            .execution_options(synchronize_session=False)
        )
