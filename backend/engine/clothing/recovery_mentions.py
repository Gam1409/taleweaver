"""Surface unaccounted explicit underwear mentions; a keyword never establishes ownership."""

import re

from backend.engine.clothing.recovery_schema import RecoveryProposal

PATTERNS = {
    "underwear_bottom": re.compile(
        r"\b(?:трус(?:ы|ов|ами|ах|ам|ик\w*)|стринг\w*|panties|underpants|thongs?|briefs|boxers)\b",
        re.IGNORECASE,
    ),
    "underwear_top": re.compile(
        r"\b(?:лифчик\w*|бюстгальтер\w*|bras?|brassieres?)\b", re.IGNORECASE
    ),
}
LABELS = {"underwear_bottom": "Underwear bottoms", "underwear_top": "Bra"}


def explicit_mentions(context: dict) -> list[dict]:
    result = []
    for kind, pattern in PATTERNS.items():
        sources = _sources(context["messages"], pattern)
        if sources:
            result.append({"kind": kind, "label": LABELS[kind], "sources": sources[-3:]})
    return result


def _sources(messages: list[dict], pattern: re.Pattern) -> list[dict]:
    sources = []
    for row in messages:
        match = pattern.search(row["content"]) if row["role"] == "assistant" else None
        if match:
            sources.append(
                {
                    "source_message_id": row["id"],
                    "excerpt": row["content"][max(0, match.start() - 100) : match.end() + 160],
                }
            )
    return sources


def mention_checks(context: dict, proposal: RecoveryProposal) -> list[dict]:
    names = [
        entry.action.new_item.name
        if entry.action.new_item
        else str(context["snapshot"].items.get(entry.action.item_id, {}).get("name", ""))
        for entry in proposal.entries
    ]
    sources = {
        row["id"]: row["content"] for row in context["messages"] if row["role"] == "assistant"
    }
    return [_check(row, names, sources, proposal) for row in explicit_mentions(context)]


def _check(mention: dict, names: list[str], sources: dict, proposal: RecoveryProposal) -> dict:
    if any(PATTERNS[mention["kind"]].search(name) for name in names):
        return {**mention, "status": "proposed"}
    omissions = [
        row
        for row in proposal.omitted_mentions
        if row.kind == mention["kind"] and row.evidence in sources.get(row.source_message_id, "")
    ]
    if omissions:
        return {
            **mention,
            "status": "explained",
            "omissions": [row.model_dump() for row in omissions],
        }
    return {**mention, "status": "unreviewed"}


def unreviewed_feedback(checks: list[dict]) -> list[str]:
    return [
        f"Unaccounted explicit mention: {row['label']}. Return an evidence-backed garment entry if still owned, or omitted_mentions with kind={row['kind']}, a reason and an exact source quote. Keywords alone do not establish ownership."
        for row in checks
        if row["status"] == "unreviewed"
    ]
