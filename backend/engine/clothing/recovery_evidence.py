"""Explain rejected recovery evidence without guessing facts or rewriting quotations."""

from backend.engine.clothing.recovery_schema import RecoveryEntry
from backend.engine.clothing.schema import Garment
from backend.engine.narrated_items.schema import ItemAction


def evidence_issues(
    entry: RecoveryEntry, action: ItemAction, source: dict, garment: Garment | None
) -> list[str]:
    issues = []
    if action.basis not in {"completed", "observed_wear"}:
        issues.append(
            f"Action basis '{action.basis}' is not a confirmed event or wear observation."
        )
    if action.evidence not in source["content"]:
        issues.append(
            "Item quote is not an exact contiguous substring of the cited assistant message. Copy the original words without translation, paraphrase or combined fragments."
        )
    if action.basis == "observed_wear" and action.disposition != "worn":
        issues.append(
            "observed_wear requires disposition=worn; completed removal uses completed/carried."
        )
    if action.attachment_slot:
        if source["content"].count(action.evidence) != 1:
            issues.append(
                "Body placement needs one unambiguous exact source quote; select a longer passage."
            )
        return issues
    return issues + _placement_issues(entry, action, source, garment)


def _placement_issues(
    entry: RecoveryEntry, action: ItemAction, source: dict, garment: Garment | None
) -> list[str]:
    issues: list[str] = []
    if not entry.uncovered_regions and not entry.placement_evidence and not entry.restore_coverage:
        return issues
    if action.disposition != "worn":
        issues.append("Partial placement requires a garment that is still worn.")
    if entry.restore_coverage and entry.uncovered_regions:
        issues.append("Restored coverage cannot also expose regions.")
    if entry.placement_evidence and not entry.uncovered_regions and not entry.restore_coverage:
        issues.append("Confirm restore_coverage before resetting an existing placement.")
    coverage = garment.coverage if garment else []
    invalid = sorted(set(entry.uncovered_regions) - set(coverage))
    if invalid:
        issues.append(
            f"Exposed regions {', '.join(invalid)} are outside garment coverage {', '.join(coverage)}."
        )
    if (entry.uncovered_regions or entry.restore_coverage) and not entry.placement_evidence:
        issues.append("Partial placement has no evidence quote.")
    elif entry.placement_evidence not in source["content"]:
        issues.append(
            "Placement quote is not an exact contiguous substring of the same cited assistant message."
        )
    return issues


def rejected_entry(
    index: int, entry: RecoveryEntry, label: str, reasons: list[str], garment: Garment | None = None
) -> dict:
    return {
        "index": index,
        "label": label,
        "source_message_id": entry.source_message_id,
        "basis": entry.action.basis,
        "disposition": entry.action.disposition,
        "evidence": entry.action.evidence,
        "placement_evidence": entry.placement_evidence,
        "coverage": garment.coverage if garment else [],
        "uncovered_regions": entry.uncovered_regions,
        "reasons": reasons,
        **(
            {"attachment_slot": entry.action.attachment_slot}
            if entry.action.attachment_slot
            else {}
        ),
        **({"restore_coverage": True} if entry.restore_coverage else {}),
    }
