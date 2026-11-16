"""Bounded visual state with provenance, invalidation and audience projections."""

import hashlib
import json
from collections import Counter
from copy import deepcopy
from typing import Any

from pydantic import TypeAdapter, ValidationError

from backend.engine.scene_staging import props
from backend.engine.scene_staging.schema import Placement, Posture, SceneDelta, SceneExtraction
from backend.engine.visual_novel.config import read_settings

KEY = "__scene_staging__"
_POSTURE: TypeAdapter[Posture] = TypeAdapter(Posture)


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def registry(state: Any) -> dict:
    value = (state.entity_states or {}).get(KEY)
    return value if isinstance(value, dict) else {}


def _origin(person: dict) -> str:
    return str(person.get("position") or "")


def retained(state: Any, cast: list[dict]) -> dict:
    data = registry(state)
    if data.get("scene_id") != state.current_scene_id or data.get("status") != "ready":
        return {}
    rows = data.get("actors", {})
    if not isinstance(rows, dict):
        return {}
    present = {person["id"]: person for person in cast}
    actors = {}
    for person in cast:
        row = deepcopy(rows.get(person["id"], {}))
        if not isinstance(row, dict) or not row or row.get("origin") != _origin(person):
            continue
        placement = row.get("placement", {})
        if not isinstance(placement, dict):
            row.pop("placement", None)
            placement = {}
        if placement.get("target_kind") == "character" and (
            placement.get("target") not in present
            or placement.get("target_origin") != _origin(present[placement["target"]])
        ):
            row.pop("placement", None)
        actors[person["id"]] = row
    return actors


def _validate_explicit(
    extraction: SceneExtraction, known: dict, narration: str, source: str
) -> tuple[list[dict], int]:
    """Drop invalid explicit atoms individually; they never veto posture facts."""
    atoms: list[dict] = []
    rejected = 0
    for delta in extraction.explicit:
        participants = list(dict.fromkeys(delta.participants))
        minimum = 1 if delta.category in ("masturbation", "exposure", "undressing") else 2
        if (
            any(participant not in known for participant in participants)
            or len(participants) < minimum
            or delta.evidence not in narration
            or (
                delta.evidence_span is not None
                and not delta.evidence_span.matches(narration, delta.evidence)
            )
        ):
            rejected += 1
            continue
        atoms.append(
            {
                "category": delta.category,
                "participants": participants,
                "evidence": delta.evidence,
                "source_hash": source,
                **(
                    {"evidence_span": delta.evidence_span.model_dump()}
                    if delta.evidence_span
                    else {}
                ),
            }
        )
    return atoms, rejected


def reconcile(
    state: Any,
    cast: list[dict],
    narration: str,
    extraction: SceneExtraction,
    *,
    unconfirmed_actors: set[str] | None = None,
    invalid_changes: int = 0,
) -> dict:
    """Quotes ground proposals; semantic accuracy still depends on the extractor."""
    known = {person["id"]: person for person in cast}
    actors = retained(state, cast)
    uncertain = set(unconfirmed_actors or ()) & known.keys()
    counts = Counter(change.entity_id for change in extraction.changes)
    rejected = invalid_changes
    moved = set()
    explicit_placements = set()
    source = digest(narration)
    for change in extraction.changes:
        placement = change.placement
        invalid_target = (
            placement is not None
            and placement.relation != "unknown"
            and (
                (
                    placement.target_kind == "character"
                    and (placement.target not in known or placement.target == change.entity_id)
                )
                or (
                    placement.target_kind == "scene_object"
                    and (not placement.target or placement.target not in change.evidence)
                )
            )
        )
        if (
            change.entity_id not in known
            or change.entity_id in uncertain
            or counts[change.entity_id] > 1
            or change.evidence not in narration
            or (
                change.evidence_span is not None
                and not change.evidence_span.matches(narration, change.evidence)
            )
            or invalid_target
        ):
            rejected += 1
            if change.entity_id in known:
                uncertain.add(change.entity_id)
            continue
        row = {} if change.clear else actors.get(change.entity_id, {})
        if (
            change.clear
            or placement is not None
            or (
                change.posture is not None and change.posture != row.get("posture", {}).get("value")
            )
        ):
            moved.add(change.entity_id)
        if placement is not None:
            explicit_placements.add(change.entity_id)
        actors[change.entity_id] = _apply_change(row, change, known, source)
    for actor_id in uncertain:
        actors.pop(actor_id, None)
    moved.update(uncertain)
    for actor_id, row in actors.items():
        placement_data = row.get("placement", {})
        if (
            actor_id not in explicit_placements
            and placement_data.get("target_kind") == "character"
            and placement_data.get("target") in moved
        ):
            row.pop("placement", None)
    explicit, explicit_rejected = _validate_explicit(extraction, known, narration, source)
    return {
        "scene_id": state.current_scene_id,
        "status": "ready",
        "source_hash": source,
        "rejected": rejected,
        "actors": actors,
        "unconfirmed_actors": sorted(uncertain),
        "explicit": explicit,
        "explicit_rejected": explicit_rejected,
    }


def _apply_change(row: dict, change: SceneDelta, known: dict, source: str) -> dict:
    proof: dict[str, Any] = {"evidence": change.evidence, "source_hash": source}
    if change.evidence_span is not None:
        proof["evidence_span"] = change.evidence_span.model_dump()
    if change.posture is not None:
        if change.posture != row.get("posture", {}).get("value"):
            row.pop("placement", None)
        row.pop("posture", None)
        if change.posture != "unknown":
            row["posture"] = {"value": change.posture, **proof}
    placement = change.placement
    row["origin"] = _origin(known[change.entity_id])
    if placement is None:
        return row
    row.pop("placement", None)
    if placement.relation == "unknown":
        return row
    row["placement"] = {**placement.model_dump(), **proof}
    if placement.target_kind == "character":
        row["placement"]["target_origin"] = _origin(known[placement.target])
    return row


def project(state: Any, cast: list[dict]) -> dict[str, dict]:
    if not read_settings(state).scene_staging:
        return {}
    actors = retained(state, cast)
    return {key: _project_actor(row) for key, row in actors.items()}


def _project_actor(row: dict) -> dict:
    result: dict[str, Any] = {}
    try:
        if row.get("posture"):
            result["posture"] = _POSTURE.validate_python(row["posture"]["value"])
        if row.get("placement"):
            value = Placement.model_validate(
                {key: row["placement"][key] for key in ("relation", "target_kind", "target")}
            )
            result["placement"] = value.model_dump()
    except (KeyError, TypeError, ValidationError):
        return {}  # A corrupt legacy actor is unknown without hiding other actors.
    return result


def narration_block(state: Any, entities: list[Any], avatar: Any) -> str:
    if not read_settings(state).scene_staging:
        return ""
    from backend.engine.npc_presence import physically_present

    cast = [{"id": avatar.id, "name": avatar.name}]
    for entity in entities:
        override = (state.entity_states or {}).get(entity.id) or {}
        location = override.get("current_scene_id", entity.current_scene_id)
        if (
            entity.entity_type != "NPC"
            or location != state.current_scene_id
            or override.get("is_hidden", entity.is_hidden)
            or not physically_present(entity, state)
        ):
            continue
        cast.append(
            {
                "id": entity.id,
                "name": entity.name,
                "position": override.get("spatial_position", entity.spatial_position),
            }
        )
    facts = project(state, cast)
    items = props.candidates(
        avatar, entities, state, {entity.id for entity in entities if entity.entity_type == "NPC"}
    )
    placed = props.project(state, items)
    if not any(facts.values()) and not placed:
        return ""
    return (
        "\nESTABLISHED SCENE STAGING (data, not narrative material):\n"
        + json.dumps({"characters": facts, "placed_items": placed}, ensure_ascii=False)
        + "\nKeep these facts consistent without listing or repeating them. Mention only "
        "meaningful changes. Unknown details stay unknown. This does not authorize "
        "movement between scenes, item transfers or clothing changes.\n"
    )
