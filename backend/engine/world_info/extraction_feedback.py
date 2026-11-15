"""Bounded correction diagnostics contain local IDs, never source or provider text."""

from collections import Counter

from backend.engine.world_info.extraction_contracts import ExtractionProposal


def describe(response: object) -> dict:
    try:
        proposal = ExtractionProposal.model_validate(response)
    except ValueError:
        return {"code": "invalid_schema"}
    facts = [fact.id for fact in proposal.facts]
    entries = [entry.id for entry in proposal.entries]
    if len(set(facts)) != len(facts) or len(set(entries)) != len(entries):
        return {"code": "duplicate_local_ids"}
    grouped = Counter(key for entry in proposal.entries for key in entry.fact_ids)
    missing = sorted(set(facts) - grouped.keys())
    unknown = sorted(grouped.keys() - set(facts))
    repeated = sorted(key for key, count in grouped.items() if count > 1)
    if missing or unknown or repeated:
        return {
            "code": "incomplete_fact_grouping",
            "unassigned_fact_ids": missing,
            "unknown_fact_ids": unknown,
            "repeated_fact_ids": repeated,
            "instruction": (
                "Assign every proposed fact to exactly one entry using supported semantic groups. "
                "Respect the per-entry fact limit; add another entry when needed. "
                "Retain supported facts and their exact evidence; do not invent references."
            ),
        }
    return {"code": "invalid_evidence_or_limits"}
