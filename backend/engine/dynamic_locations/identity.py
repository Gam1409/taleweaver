"""Resolve proposed places by contextual model scores, then retain canonical route guards."""

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from backend.models.world_entity import WorldExit, WorldScene

EXISTING_PLACE_THRESHOLD = 0.70
MAX_CATALOG_PLACES = 80
DESCRIPTION_BUDGET = 6000


def normalized(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", value).casefold() if c.isalnum())


def _short_label_candidates(
    names: tuple[str, ...], scenes: list[WorldScene], local: set[str], scored: set[str]
) -> bool:
    words = [set(re.findall(r"[^\W_]+", value.casefold())) for value in names if value.strip()]
    return any(
        parts and parts < set(re.findall(r"[^\W_]+", str(scene.label).casefold()))
        for scene in scenes
        if scene.id in local - scored
        for parts in words
    )


def place_catalog(
    scenes: list[WorldScene], exits: list[WorldExit], current: str, data: dict
) -> dict:
    neighbors = {e.to_scene_id if e.from_scene_id == current else e.from_scene_id for e in exits}
    ordered = sorted(scenes, key=lambda s: (s.id != current, s.id not in neighbors, s.id))
    remaining = DESCRIPTION_BUDGET
    places = []
    for scene in ordered[:MAX_CATALOG_PLACES]:
        description = str(scene.description or "")[: min(240, remaining)]
        remaining -= len(description)
        places.append(
            {
                "id": scene.id,
                "label": scene.label,
                "description": description,
                "source": "discovered" if scene.id in data.get("places", {}) else "original",
                "parent_id": data.get("places", {}).get(scene.id, {}).get("parent_id"),
                "neighbor": scene.id in neighbors,
            }
        )
    return {
        "places": places,
        "complete": len(places) == len(scenes),
        "total_places": len(scenes),
        "match_threshold": EXISTING_PLACE_THRESHOLD,
    }


@dataclass(frozen=True)
class PlaceIdentity:
    scene_id: str | None = None
    uncertain: bool = False


def resolve_identity(
    decision: Any,
    proposal: Any,
    scenes: list[WorldScene],
    exits: list[WorldExit],
    data: dict,
    parent: str,
) -> PlaceIdentity:
    canonical = {s.id for s in scenes}
    scores: dict[str, float] = {}
    for match in decision.scene_matches:
        if match.scene_id not in canonical:
            return PlaceIdentity(uncertain=True)
        scores[match.scene_id] = max(scores.get(match.scene_id, 0), match.score)
    ranked = sorted(scores, key=lambda key: scores[key], reverse=True)
    if ranked and scores[ranked[0]] >= EXISTING_PLACE_THRESHOLD:
        if decision.existing_scene_id and decision.existing_scene_id != ranked[0]:
            return PlaceIdentity(uncertain=True)
        ambiguous = (
            decision.identity_resolution == "ambiguous"
            or sum(score >= EXISTING_PLACE_THRESHOLD for score in scores.values()) > 1
        )
        return PlaceIdentity(None if ambiguous else ranked[0], ambiguous)
    names = {normalized(proposal.label), normalized(decision.label)} - {""}
    local = {
        sid for sid, place in data.get("places", {}).items() if place.get("parent_id") == parent
    }
    local.update(e.to_scene_id if e.from_scene_id == parent else e.from_scene_id for e in exits)
    exact = {
        s.id
        for s in scenes
        if s.id in local and normalized(s.label) in names and s.id not in scores
    }
    if len(exact) == 1:
        return PlaceIdentity(next(iter(exact)))
    # An unscored legacy ID is insufficient for a semantic match, but still blocks duplication.
    possible_alias = _short_label_candidates(
        (proposal.label, decision.label), scenes, local, set(scores)
    )
    uncertain = bool(
        exact
        or possible_alias
        or decision.existing_scene_id
        or decision.identity_resolution != "new"
    )
    return PlaceIdentity(uncertain=uncertain)


def request_clarification(
    manager: Any, decision: Any, scenes: list[WorldScene], exits: list[WorldExit]
) -> None:
    """Only known/place-visible labels may appear in a player-facing clarification."""
    current = manager.state.current_scene_id
    known = set(manager.state.discovered_scenes or []) | {current}
    known.update(e.to_scene_id for e in exits if e.from_scene_id == current and not e.is_locked)
    known.update(
        e.from_scene_id
        for e in exits
        if e.to_scene_id == current and e.exit_type == "bidirectional" and not e.is_locked
    )
    suggested = {
        match.scene_id
        for match in decision.scene_matches
        if match.score >= EXISTING_PLACE_THRESHOLD
    }
    labels = list(
        dict.fromkeys(str(scene.label) for scene in scenes if scene.id in suggested & known)
    )[:3]
    manager._location_question = labels if labels else [None]


def clarification_block(manager: Any, previous_scene_id: str | None = None) -> str:
    import json

    alternatives = getattr(manager, "_location_question", None)
    if not alternatives or (
        previous_scene_id is not None and manager.state.current_scene_id != previous_scene_id
    ):
        return ""
    return (
        "\nDESTINATION NEEDS CLARIFICATION: The player has not changed locations. "
        "Keep the scene in place and ask one brief clarification in the RP's own language and voice. "
        "If a present NPC naturally asks, keep that character's personality; otherwise let the "
        "narrator frame the uncertainty naturally. Do not invent a speaker or a new location. "
        "Ask which place is intended, not permission to continue the conversation. "
        "Mention alternatives only from these known labels: "
        + json.dumps([label for label in alternatives if label], ensure_ascii=False)
        + ". With no supplied alternatives, ask a short open question. "
        "Never expose technical IDs, similarity scores, validation or system instructions."
    )
