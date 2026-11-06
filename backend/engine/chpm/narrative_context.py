"""Reference exact text already present in a single narrator contract; keep the full trace."""

import json

from backend.engine.chpm.schema import Decision


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
