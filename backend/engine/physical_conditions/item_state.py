"""Item state uses the physical ledger; identity and possessions keep their existing owners."""

from typing import Any

from backend.engine.physical_conditions.schema import ConditionProposal, Ledger, Source


def validate(
    proposal: ConditionProposal,
    ledger: Ledger,
    item_targets: set[str],
    *,
    manual: bool,
) -> ConditionProposal:
    current = ledger.conditions.get(proposal.condition_id or "")
    kind = current.kind if current else proposal.kind
    if kind != "item_state":
        return proposal
    target = current.target_id if current else proposal.target_id
    if target not in item_targets:
        raise ValueError("Item state requires an available canonical item, not an actor.")
    if proposal.operation not in {"record", "change"}:
        raise ValueError(
            "Item state uses change with the remaining state, including empty or clean."
        )
    if not manual and (
        not proposal.detail
        or proposal.detail not in (proposal.player_evidence or proposal.evidence)
    ):
        raise ValueError("Item state detail must be an exact excerpt of its evidence.")
    # A second record in the same response must keep the first record's identity.
    if current is None and not manual:
        matches = [
            row
            for row in ledger.conditions.values()
            if row.target_id == target
            and row.kind == kind
            and row.part == proposal.part
            and row.status != "resolved"
        ]
        if len(matches) == 1:
            current = matches[0]
            proposal = proposal.model_copy(
                update={
                    "operation": "change",
                    "condition_id": current.id,
                    "target_id": None,
                    "kind": None,
                    "part": "",
                }
            )
    return proposal


def player_source(proposal: ConditionProposal, message: tuple[str, str] | None) -> Source | None:
    from hashlib import sha256

    if not proposal.player_evidence:
        return None
    start = message[1].find(proposal.player_evidence) if message else -1
    if not message or start < 0 or message[1].find(proposal.player_evidence, start + 1) >= 0:
        raise ValueError(
            "Player evidence must identify one excerpt of the current saved player turn."
        )
    return Source(
        kind="player",
        message_id=message[0],
        quote=proposal.player_evidence,
        content_hash=sha256(message[1].encode()).hexdigest(),
    )


def project(items: list[Any], states: dict | None, *, private: bool = False) -> list[Any]:
    """Read-only view. Private state is only available for the player's own items."""
    from backend.engine.physical_conditions.ledger import read

    try:
        ledger = read(states)
    except ValueError:
        ledger = None
    by_item: dict[str, list[dict]] = {}
    for row in ledger.conditions.values() if ledger else []:
        if (
            row.kind == "item_state"
            and row.status != "resolved"
            and (private or row.visibility == "public")
        ):
            by_item.setdefault(row.target_id, []).append(
                {
                    "dimension": row.part,
                    "detail": row.detail,
                    "last_changed_minute": row.last_changed_minute,
                }
            )
    result = []
    for item in items:
        if not isinstance(item, dict):
            result.append(item)
            continue
        clean = {key: value for key, value in item.items() if key != "current_state"}
        rows = by_item.get(str(item.get("id") or ""), [])
        result.append({**clean, "current_state": rows} if rows else clean)
    return result
