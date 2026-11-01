"""Fail visibly on missing literal anchors and incompatible supported pose extraction.

Literal coverage is not semantic proof. The optional pose checker is fallible and
must never rewrite canonical facts. At most one feedback retry is permitted.
"""

import re

from backend.core.visual_trace import record
from backend.engine.clothing.frames import extract_frame
from backend.models.user import User

POSTURES = {"seated": "sitting", "unspecified": "unknown"}


def anchors(facts: dict) -> list[str]:
    values = []
    for person in facts.get("characters", []):
        values.append(str(person.get("name") or ""))
        values.extend(person.get("clothing_tokens") or [])
        placement = person.get("placement") or {}
        if placement.get("target_kind") == "scene_object":
            values.append(placement.get("target", ""))
    for item in facts.get("props", []):
        values.extend([item.get("name", ""), item.get("spatial_position", "")])
    return list(dict.fromkeys(value for value in values if value))


def literal_diff(body: str, facts: dict) -> list[str]:
    folded = " ".join(body.casefold().split())
    missing = [
        value for value in anchors(facts) if " ".join(value.casefold().split()) not in folded
    ]
    count = len(facts.get("characters", []))
    counts = [
        int(value) for value in re.findall(r"\b(\d+)\s+(?:people|characters|persons)\b", folded)
    ]
    if count and (not counts or any(value != count for value in counts)):
        missing.append(f"{count} people")
    return missing


def requirements(facts: dict) -> str:
    import json

    return (
        "\nLiteral fidelity contract: include the exact character names, visible item names "
        "and confirmed prop positions from these anchors, without translating or abbreviating them: "
        + json.dumps(anchors(facts), ensure_ascii=False)
        + f". Include '{len(facts.get('characters', []))} people' as the cast count. "
        "These describe the image, never lettering or captions. Bind each item to its saved owner/placement."
    )


async def differences(body: str, facts: dict, user: User) -> list[str]:
    missing = literal_diff(body, facts)
    record("fidelity.literal", missing=missing)
    if missing:
        return [f"Missing literal anchor: {value}" for value in missing]
    expected = [
        person
        for person in facts.get("characters", [])
        if person.get("posture") and person["posture"] != "unknown"
    ]
    relationships = [
        (person, person.get("placement") or {}) for person in facts.get("characters", [])
    ]
    relationships = [
        (person, placement)
        for person, placement in relationships
        if placement.get("target_kind") == "character"
        and placement.get("relation") in {"beside", "behind", "in_front_of", "near"}
    ]
    if not expected and not relationships:
        return []
    frame = await extract_frame(user, body, facts["characters"])
    actual = {figure.character_id: figure for figure in frame.figures}
    mismatches = []
    for person in expected:
        figure = actual.get(person["id"])
        posture = POSTURES.get(figure.posture, figure.posture) if figure else "unknown"
        if not figure or figure.presence != "visible" or posture != person["posture"]:
            mismatches.append(f"Preserve {person['name']}: {person['posture']}.")
    relations = {(r.subject_id, r.target_id, r.relation) for r in frame.relations}
    for person, placement in relationships:
        if (person["id"], placement["target"], placement["relation"]) not in relations:
            mismatches.append(f"Preserve {person['name']} placement: {placement}.")
    record("fidelity.poses", mismatches=mismatches)
    return mismatches
