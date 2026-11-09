"""Copy-on-write facts: silence never ends a process or resolves its effects."""

from copy import deepcopy
from hashlib import sha256
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from pydantic import ValidationError

from .schema import KEY, MAX_RECORDS, MAX_UPDATES, Action, Evidence, Ledger, Record, Update


def digest(text: str) -> str:
    return sha256(text.encode()).hexdigest()


def read(states: dict | None) -> Ledger:
    raw = (states or {}).get(KEY)
    try:
        return Ledger.model_validate({} if raw is None else raw)
    except ValidationError as exc:
        raise ValueError("Stored scene continuity is invalid and was preserved.") from exc


def _source(update: Update, message: Any, scene_description: str, scene_id: str) -> Evidence:
    text = message.content if update.source == "narration" else scene_description
    if update.evidence not in text:
        raise ValueError("Evidence must be an exact contiguous quote from its declared source.")
    return Evidence(
        kind=update.source,
        source_id=message.id if update.source == "narration" else scene_id,
        revision_id=getattr(message, "revision_id", None) if update.source == "narration" else None,
        content_hash=digest(text),
        quote=update.evidence,
    )


def _new(
    ledger: Ledger, update: Update, source: Evidence, *, scene_id: str, session_id: str, minute: int
) -> Record:
    identifier = (
        "scene_fact_"
        + uuid5(
            NAMESPACE_URL, f"{session_id}:{scene_id}:{update.subject_id}:{update.kind}:{update.key}"
        ).hex
    )
    if identifier in ledger.records or any(
        row.scene_id == scene_id
        and row.subject_id == update.subject_id
        and row.kind == update.kind
        and row.key == update.key
        for row in ledger.records.values()
    ):
        raise ValueError("This fact already exists; reference its record_id to change it.")
    if len(ledger.records) >= MAX_RECORDS:
        raise ValueError("Scene fact capacity reached; previous facts were preserved.")
    return Record(
        id=identifier,
        key=update.key,
        scene_id=scene_id,
        subject_id=update.subject_id,
        kind=update.kind,
        detail=update.detail,
        visual_detail=update.visual_detail,
        visibility=update.visibility,
        observers=update.observers,
        cause_id=update.cause_id,
        origin=source,
        latest=source,
        recorded_minute=minute,
        updated_minute=minute,
        review_at_minute=minute + update.review_after_minutes
        if update.review_after_minutes
        else None,
    )


def _changed(ledger: Ledger, update: Update, source: Evidence, minute: int) -> Record:
    current = ledger.records.get(update.record_id)
    if current is None or current.status == "ended":
        raise ValueError("Changing a fact requires an existing non-ended record.")
    if minute < current.updated_minute:
        raise ValueError("A scene update cannot precede its saved game minute.")
    row = current.model_copy(deep=True)
    row.detail = update.detail or row.detail
    row.visual_detail = update.visual_detail if update.operation != "end" else ""
    row.visibility, row.observers = update.visibility, update.observers
    row.status = "ended" if update.operation == "end" else "active"
    row.latest, row.updated_minute = source, minute
    row.review_at_minute = (
        minute + update.review_after_minutes if update.review_after_minutes else None
    )
    if update.cause_id:
        row.cause_id = update.cause_id
    return row


def _validate(row: Record, ledger: Ledger, targets: set[str], scene_id: str) -> None:
    if row.scene_id != scene_id or row.subject_id not in targets:
        raise ValueError("Scene facts require a current, accessible subject in this scene.")
    if row.kind == "environment" and row.subject_id != scene_id:
        raise ValueError("Environment facts describe the room, never a character or outfit.")
    if not set(row.observers).issubset(targets):
        raise ValueError("Private observers must be current session subjects.")
    if row.cause_id and (row.cause_id not in ledger.records or row.cause_id == row.id):
        raise ValueError("A consequence must reference an existing distinct cause.")
    # A temporal edge must point backwards; changing an old record cannot create a cycle.
    cause = ledger.records.get(row.cause_id)
    if cause and cause.recorded_minute > row.recorded_minute:
        raise ValueError("A consequence cannot predate its recorded cause.")
    visited = {row.id}
    while cause is not None:
        if cause.id in visited:
            raise ValueError("Causal scene links cannot form a cycle.")
        visited.add(cause.id)
        cause = ledger.records.get(cause.cause_id)


def apply(
    states: dict | None,
    updates: list[Any],
    actions: list[Any],
    *,
    message: Any,
    scene_id: str,
    scene_description: str,
    session_id: str,
    minute: int,
    targets: set[str],
    actor_targets: set[str] | None = None,
) -> tuple[dict, list[str]]:
    ledger = read(states).model_copy(deep=True)
    if ledger.last_check.get("message_id") == message.id and ledger.last_check.get(
        "hash"
    ) == digest(message.content):
        return deepcopy(states or {}), []
    if type(minute) is not int or minute < 0:
        raise ValueError("Scene continuity requires a nonnegative game minute.")
    errors = []
    entries = updates if len(updates) <= MAX_UPDATES else []
    if updates and not entries:
        errors.append("Scene update batch exceeds its limit; previous facts were preserved.")
    for index, raw in enumerate(entries):
        try:
            update = Update.model_validate(raw)
            source = _source(update, message, scene_description, scene_id)
            row = (
                _new(
                    ledger, update, source, scene_id=scene_id, session_id=session_id, minute=minute
                )
                if update.operation == "record"
                else _changed(ledger, update, source, minute)
            )
            if row.visibility == "public":
                row.observers = sorted(actor_targets or {"__player__"})
            row = Record.model_validate(row.model_dump())
            _validate(row, ledger, targets, scene_id)
            ledger.records[row.id] = row
        except (ValueError, ValidationError):
            errors.append(f"Scene update {index + 1} failed schema, source or subject validation.")
    ledger.frame_actions, action_errors = _actions(
        actions, message.content, actor_targets if actor_targets is not None else targets
    )
    errors.extend(action_errors)
    ledger.frame_message_id = message.id
    ledger.last_check = {
        "message_id": message.id,
        "hash": digest(message.content),
        "minute": minute,
        "rejected": errors,
    }
    result = deepcopy(states or {})
    result[KEY] = Ledger.model_validate(ledger.model_dump()).model_dump()
    return result, errors


def _actions(
    values: list[Any], narration: str, targets: set[str]
) -> tuple[list[Action], list[str]]:
    if len(values) > 4:
        return [], ["Final-frame actions exceed their limit."]
    accepted, errors = [], []
    for raw in values:
        try:
            row = Action.model_validate(raw)
            if row.evidence not in narration or not set(row.actor_ids).issubset(targets):
                raise ValueError("Final-frame action source or actors are unavailable.")
            accepted.append(row)
        except (ValueError, ValidationError):
            errors.append("A final-frame action failed source or actor validation.")
    return accepted, errors
