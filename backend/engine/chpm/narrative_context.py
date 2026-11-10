"""Reference exact text already present in a single narrator contract; keep the full trace."""

import json

from backend.engine.chpm.core.contracts import Experience
from backend.engine.chpm.core.history import events
from backend.engine.chpm.host_state import Mind
from backend.engine.chpm.schema import Decision

EXPERIENCE_REASON_LIMIT = 2
EXPERIENCE_REASON_EXTRA_CHARS = 512


def experience_reasons(mind: Mind, view: dict) -> dict:
    """Share bounded stored reasons without refreshing their age or mutating the mind."""
    if not view["states"]:
        return view
    reasons = {
        event.payload.record_id: event.payload.explanation
        for event in events(mind.snapshot)
        if isinstance(event.payload, Experience) and event.scope == mind.genesis.scope
    }
    result = {**view, "states": [dict(row) for row in view["states"]]}
    candidates = sorted(
        (row for row in result["states"] if reasons.get(row["record_id"])),
        key=lambda row: (
            row["status"] != "recent_appraisal",
            row["channel"] != "affect",
            -row["assessed_at_minute"],
        ),
    )
    result["omitted_reasons"] = len(candidates)
    baseline = _size(view)
    for row in candidates[:EXPERIENCE_REASON_LIMIT]:
        row["last_assessed_reason"] = reasons[row["record_id"]]
        if _size(result) - baseline > EXPERIENCE_REASON_EXTRA_CHARS:
            row.pop("last_assessed_reason")
            continue
        result["omitted_reasons"] -= 1
    return result


def compact_motives(decision: Decision, contract: dict) -> list[dict]:
    references = _strings(contract.get("authored_identity", {}), "/authored_identity")
    references.update(
        _strings(contract.get("agent_observed_sources", []), "/agent_observed_sources")
    )
    references.update(
        _strings(
            contract.get("subjective_assessments_not_world_facts", []),
            "/subjective_assessments_not_world_facts",
        )
    )
    references.update(
        _strings(
            contract.get("ongoing_agenda_not_world_facts", []), "/ongoing_agenda_not_world_facts"
        )
    )
    result = []
    for motive in decision.candidate_motives.get(decision.selected.kind, []):
        entry = motive.model_dump()
        # Canonical bindings remain in the saved trace; hashes are not prose evidence.
        entry["source"].pop("provenance_id")
        text = entry["source"]["text"]
        path = references.get(text)
        if path and _size({"text_ref": path}) < _size({"text": text}):
            entry["source"].pop("text")
            entry["source"]["text_ref"] = path
        result.append(entry)
    return result


def _size(value: dict) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def _strings(value: object, path: str) -> dict[str, str]:
    if isinstance(value, str):
        return {value: path}
    if isinstance(value, list):
        return {
            text: pointer
            for index, item in enumerate(value)
            for text, pointer in _strings(item, path + "/" + str(index)).items()
        }
    if isinstance(value, dict):
        return {
            text: pointer
            for key, item in value.items()
            for text, pointer in _strings(
                item, path + "/" + str(key).replace("~", "~0").replace("/", "~1")
            ).items()
        }
    return {}
