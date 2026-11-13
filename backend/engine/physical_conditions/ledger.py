"""Copy-on-write operations on physical facts; no interpretation of prose keywords."""

from copy import deepcopy
from hashlib import sha256
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from pydantic import ValidationError

from backend.core.text_evidence import require_span
from backend.engine.physical_conditions.item_state import player_source
from backend.engine.physical_conditions.item_state import validate as validate_item_state
from backend.engine.physical_conditions.schema import (
    KEY,
    MAX_ACTIVE,
    MAX_EVENTS,
    MAX_PROPOSALS,
    MAX_RESOLVED,
    Condition,
    ConditionProposal,
    Event,
    Ledger,
    Source,
    Status,
)
from backend.engine.physical_conditions.source_order import require_order
from backend.engine.physical_conditions.validation import rejection

_TRANSITIONS: dict[str, tuple[set[str], Status]] = {
    "treat": ({"injury", "pain"}, "treated"),
    "reduce": ({"injury", "contamination", "fluid", "pain", "other"}, "reduced"),
    "clean": ({"contamination", "fluid"}, "resolved"),
    "heal": ({"injury", "pain"}, "resolved"),
    "remove": ({"contamination", "fluid", "other"}, "resolved"),
}


def read(states: dict | None) -> Ledger:
    raw = (states or {}).get(KEY)
    try:
        return Ledger.model_validate({} if raw is None else raw)
    except ValidationError as exc:
        raise ValueError("Stored physical conditions are invalid; they were preserved.") from exc


def _source(proposal: ConditionProposal, narration: str, message_id: str, manual: bool) -> Source:
    require_span(narration, proposal.evidence, proposal.evidence_span)
    if not manual and proposal.evidence not in narration:
        raise ValueError("Condition evidence is not an exact quote from this completed narration.")
    return Source(
        kind="manual" if manual else "narration",
        message_id=None if manual else message_id,
        content_hash="" if manual else sha256(narration.encode()).hexdigest(),
        quote=proposal.evidence,
        evidence_span=proposal.evidence_span,
    )


def _record(
    ledger: Ledger,
    proposal: ConditionProposal,
    source: Source,
    targets: set[str],
    session_id: str,
    index: int,
    attempt: str,
    minute: int | None,
) -> Condition:
    if proposal.target_id is None or proposal.kind is None or proposal.target_id not in targets:
        raise ValueError("Condition target does not belong to the available session subjects.")
    active = [row for row in ledger.conditions.values() if row.status != "resolved"]
    if len(active) >= MAX_ACTIVE:
        raise ValueError("Active condition capacity reached; existing conditions were kept.")
    if any(
        row.target_id == proposal.target_id
        and row.kind == proposal.kind
        and row.part.casefold() == proposal.part.casefold()
        for row in active
    ):
        raise ValueError(
            "This subject already has that kind of condition on this part; use its condition ID."
        )
    identifier = "condition_" + uuid5(NAMESPACE_URL, f"{session_id}:{attempt}:{index}").hex
    return Condition(
        id=identifier,
        target_id=proposal.target_id,
        kind=proposal.kind,
        part=proposal.part,
        detail=proposal.detail,
        visibility=proposal.visibility or "private",
        **_visual_fields(proposal),
        origin=source,
        latest=source,
        updated_revision=ledger.revision + 1,
        first_recorded_minute=minute,
        last_changed_minute=minute,
    )


def _update(
    ledger: Ledger,
    proposal: ConditionProposal,
    source: Source,
    targets: set[str],
    minute: int | None,
) -> Condition:
    current = ledger.conditions.get(proposal.condition_id or "")
    if current is None or current.target_id not in targets:
        raise ValueError("Condition is unknown or belongs to an unavailable subject.")
    if current.status == "resolved":
        raise ValueError(
            "A resolved condition cannot be reopened by an update; record a new event."
        )
    changed = current.model_copy(deep=True)
    if proposal.operation != "change":
        allowed, status = _TRANSITIONS[proposal.operation]
        if current.kind not in allowed:
            raise ValueError("This operation cannot resolve or treat this kind of condition.")
        changed.status = status
    if proposal.detail:
        changed.detail = proposal.detail
    if proposal.visibility is not None:
        changed.visibility = proposal.visibility
    changed.latest = source
    visual = _visual_fields(proposal)
    changed.visual_detail, changed.visual_region = visual["visual_detail"], visual["visual_region"]
    changed.updated_revision = ledger.revision + 1
    fact_fields: tuple[str, ...] = ("status", "detail", "visibility")
    if current.kind != "item_state":
        fact_fields += ("visual_detail", "visual_region")
    if any(getattr(changed, field) != getattr(current, field) for field in fact_fields):
        changed.last_changed_minute = minute
    return changed


def _visual_fields(proposal: ConditionProposal) -> dict[str, Any]:
    confirmed = bool(
        proposal.visual_detail
        and proposal.visual_region
        and proposal.visual_detail in proposal.evidence
    )
    return {
        "visual_detail": proposal.visual_detail if confirmed else "",
        "visual_region": proposal.visual_region if confirmed else None,
    }


def _retain(ledger: Ledger) -> None:
    closed = sorted(
        (row for row in ledger.conditions.values() if row.status == "resolved"),
        key=lambda row: row.updated_revision,
    )
    for row in closed[:-MAX_RESOLVED]:
        del ledger.conditions[row.id]
        ledger.archived_resolved += 1
    excess = max(0, len(ledger.events) - MAX_EVENTS)
    ledger.archived_events += excess
    ledger.events = ledger.events[-MAX_EVENTS:]


def apply(
    states: dict | None,
    proposals: list[Any],
    *,
    targets: set[str],
    narration: str,
    message_id: str,
    session_id: str,
    minute: int,
    manual: bool = False,
    item_targets: set[str] | None = None,
    player_message: tuple[str, str] | None = None,
) -> tuple[dict, list[str], list[str]]:
    """One failed operation does not erase other records or unrelated accepted operations."""
    ledger = read(states).model_copy(deep=True)
    if ledger.last_check.get("message_id") == message_id:
        return deepcopy(states or {}), [], []
    accepted: list[str] = []
    rejected: list[str] = []
    recorded_minute = minute if type(minute) is int and minute >= 0 else None
    entries = proposals if len(proposals) <= MAX_PROPOSALS else []
    if not entries and proposals:
        rejected.append("Too many condition proposals; this batch was not applied.")
    for index, raw in enumerate(entries):
        try:
            proposal = ConditionProposal.model_validate(raw)
            proposal = validate_item_state(proposal, ledger, item_targets or set(), manual=manual)
            require_order(
                ledger.conditions.get(proposal.condition_id or ""),
                proposal,
                narration,
                message_id,
                manual=manual,
            )
            reported_by = player_source(proposal, player_message)
            source = _source(proposal, narration, message_id, manual)
            condition = (
                _record(
                    ledger,
                    proposal,
                    source,
                    targets,
                    session_id,
                    index,
                    message_id,
                    recorded_minute,
                )
                if proposal.operation == "record"
                else _update(ledger, proposal, source, targets, recorded_minute)
            )
            if reported_by and condition.kind != "item_state":
                raise ValueError("Player reports are supported only for item state.")
            condition.reported_by = reported_by
            ledger.conditions[condition.id] = condition
            ledger.events.append(
                Event(
                    condition_id=condition.id,
                    operation=proposal.operation,
                    revision=ledger.revision + 1,
                    source=source,
                    detail=condition.detail if condition.kind == "item_state" else "",
                    minute=recorded_minute if condition.kind == "item_state" else None,
                    reported_by=reported_by,
                )
            )
            accepted.append(condition.id)
        except ValidationError as exc:
            rejected.append(rejection(index, exc))
        except ValueError as exc:
            rejected.append(f"Condition proposal {index + 1}: {exc}")
    if accepted:
        ledger.revision += 1
    _retain(ledger)
    ledger.last_check = {
        "message_id": message_id,
        "status": "needs_review" if rejected else "complete",
        "accepted": accepted,
        "rejected": rejected,
        "minute": minute,
        "proposed_count": len(proposals),
    }
    result = deepcopy(states or {})
    result[KEY] = Ledger.model_validate(ledger.model_dump()).model_dump()
    return result, accepted, rejected


def remap(states: dict | None, message_ids: dict[str, str]) -> dict:
    """Copies keep physical facts; missing historical sources are explicitly unavailable."""
    result = deepcopy(states or {})
    if KEY not in result:
        return result
    ledger = read(result)
    sources = [source for row in ledger.conditions.values() for source in (row.origin, row.latest)]
    sources.extend(event.source for event in ledger.events)
    sources.extend(row.reported_by for row in ledger.conditions.values() if row.reported_by)
    sources.extend(event.reported_by for event in ledger.events if event.reported_by)
    for source in sources:
        if source.kind not in {"narration", "player"}:
            continue
        source.message_id = message_ids.get(source.message_id or "")
        if source.message_id is None:
            source.kind = "unavailable"
    ledger.last_check["message_id"] = message_ids.get(ledger.last_check.get("message_id") or "")
    result[KEY] = ledger.model_dump()
    return result
