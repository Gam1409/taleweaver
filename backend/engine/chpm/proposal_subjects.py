"""Explain appraisal subject selectors using only the observer's offered subject list."""

import json


def problem(field: str, row: dict, subjects: list[str]) -> str | None:
    if "about_id" not in row:
        return None
    target = row["about_id"]
    affect = field == "experiences" and row.get("channel") == "affect"
    relationship = field == "developments" and row.get("category") == "relationship"
    if affect or relationship or field == "new_beliefs":
        if target in subjects or (affect and target is None):
            return None
        # Large subject lists are already present in the observer's context.
        choices = json.dumps(subjects, ensure_ascii=False)
        if len(choices) > 350:
            choices = "appraisal_context.known_subjects"
        if affect:
            return (
                f"Choose a subject from {choices} or null. For an item or situation, use null "
                "and keep its significance in the explanation and citations."
            )
        return f"Choose a subject from {choices}, or omit this unsupported entry."
    own_need = field == "experiences" and row.get("channel") in (
        "need_satisfaction",
        "need_frustration",
    )
    own_trait = field == "developments" and row.get("category") in ("trait", "habit")
    if target is not None and (own_need or own_trait):
        return "Use null. This state belongs to the observer."
    return None


def issues(candidate: dict, subjects: list[str]) -> list[dict]:
    """Collect field-specific feedback even when structural or grounding errors coexist."""
    result = []
    for field in ("experiences", "new_beliefs", "developments"):
        rows = candidate.get(field)
        if not isinstance(rows, list):
            continue
        for index, row in enumerate(rows):
            message = problem(field, row, subjects) if isinstance(row, dict) else None
            if message:
                result.append(
                    {
                        "loc": (field, index, "about_id"),
                        "type": "unavailable_subject",
                        "msg": message,
                    }
                )
    return result
