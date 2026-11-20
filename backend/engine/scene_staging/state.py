"""Bounded visual state with provenance, invalidation and audience projections."""

import hashlib
import json
from collections import Counter
from copy import deepcopy
from typing import Any

from pydantic import TypeAdapter, ValidationError

from backend.engine.scene_staging import props
from backend.engine.scene_staging.room_items import placement_targets
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


def retained(
    state: Any, cast: list[dict], scene_objects: dict[str, str | None] | None = None
) -> dict:
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
        if placement.get("target_kind") == "scene_object":
            _retain_object(state, row, placement, scene_objects)
        actors[person["id"]] = row
    return actors


def _retain_object(
    state: Any, row: dict, placement: dict, scene_objects: dict[str, str | None] | None
) -> None:
    if "target_id" not in placement and placement.get("source_kind") != "command":
        return  # Older narrated placements were grounded labels, without canonical identities.
    target_id = placement.get("target_id")
    if not isinstance(target_id, str) or _object_unavailable(state, target_id):
        row.pop("placement", None)
        return
    if scene_objects is None:
        return
    if name := scene_objects.get(target_id):
        placement["target"] = name
    else:
        row.pop("placement", None)


def _object_unavailable(state: Any, identifier: Any) -> bool:
    if not isinstance(identifier, str) or not identifier:
        return True
    override = (state.entity_states or {}).get(identifier, {})
    return not isinstance(override, dict) or bool(
        override.get("is_hidden")
        or override.get("is_in_inventory")
        or override.get("current_scene_id", state.current_scene_id) != state.current_scene_id
    )


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


def _resolve_target(
    change: SceneDelta,
    known: dict,
    scene_objects: dict[str, str | None],
    offered: frozenset[str] | None,
) -> tuple[SceneDelta, str | None, bool]:
    placement = change.placement
    if placement is None or placement.relation == "unknown":
        return change, None, True
    target = placement.target
    if placement.target_kind == "character":
        valid = target in known and target != change.entity_id
    elif target in scene_objects or (offered is not None and target in offered):
        name = scene_objects.get(target) if offered is None or target in offered else None
        if name:
            bound = placement.model_copy(update={"target": name})
            return change.model_copy(update={"placement": bound}), target, True
        valid = False
    else:
        # Unregistered scenery in existing games retains its grounded, textual placement.
        valid = (
            bool(target)
            and target in change.evidence
            and all(
                target.casefold() != label.casefold() for label in scene_objects.values() if label
            )
        )
    if valid:
        return change, None, True
    # An unresolvable placement does not invalidate an independently grounded posture.
    return change.model_copy(update={"placement": None}), None, False


def reconcile(
    state: Any,
    cast: list[dict],
    narration: str,
    extraction: SceneExtraction,
    *,
    unconfirmed_actors: set[str] | None = None,
    invalid_changes: int = 0,
    resolved_sources: dict[str, dict] | None = None,
    scene_objects: dict[str, str | None] | None = None,
    offered_objects: frozenset[str] | None = None,
) -> dict:
    """Quotes ground proposals; semantic accuracy still depends on the extractor."""
    known = {person["id"]: person for person in cast}
    actors = retained(state, cast, scene_objects)
    uncertain = set(unconfirmed_actors or ()) & known.keys()
    counts = Counter(change.entity_id for change in extraction.changes)
    rejected = invalid_changes
    moved = set()
    explicit_placements = set()
    source = digest(narration)
    for candidate in extraction.changes:
        change, target_id, valid_target = _resolve_target(
            candidate, known, scene_objects or {}, offered_objects
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
            or (not valid_target and change.posture is None)
        ):
            rejected += 1
            if change.entity_id in known:
                uncertain.add(change.entity_id)
            continue
        previous = position(actors.get(change.entity_id, {}))
        row = {} if change.clear else actors.get(change.entity_id, {})
        if not valid_target:
            rejected += 1
            row.pop("placement", None)
        if change.placement is not None:
            explicit_placements.add(change.entity_id)
        actors[change.entity_id] = _apply_change(
            row, change, known, source, (resolved_sources or {}).get(change.entity_id)
        )
        if target_id is not None:
            actors[change.entity_id]["placement"]["target_id"] = target_id
        # Repeated evidence changes provenance, not the target's actual final position.
        if position(actors[change.entity_id]) != previous:
            moved.add(change.entity_id)
    for actor_id in uncertain:
        actors.pop(actor_id, None)
    moved.update(uncertain)
    invalidated = invalidate_relations(actors, moved, explicit_placements)
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
        **({"invalidated_placements": sorted(invalidated)} if invalidated else {}),
    }


def _apply_change(
    row: dict, change: SceneDelta, known: dict, source: str, cause: dict | None = None
) -> dict:
    proof: dict[str, Any] = {"evidence": change.evidence, "source_hash": source}
    if cause is not None:
        proof.update(source_kind="external_effect", cause=deepcopy(cause))
    if change.evidence_span is not None:
        proof["evidence_span"] = change.evidence_span.model_dump()
    if change.posture is not None or change.placement is not None:
        row.pop("command", None)
    return apply_fields(
        row,
        actor_id=change.entity_id,
        posture=change.posture,
        placement=change.placement,
        known=known,
        proof=proof,
    )


def apply_fields(
    row: dict,
    *,
    actor_id: str,
    posture: Posture | None,
    placement: Placement | None,
    known: dict,
    proof: dict,
) -> dict:
    """Apply owner-validated staging fields with their actual producer's provenance."""
    if posture is not None:
        if posture != row.get("posture", {}).get("value"):
            row.pop("placement", None)
        row.pop("posture", None)
        if posture != "unknown":
            row["posture"] = {"value": posture, **proof}
    row["origin"] = _origin(known[actor_id])
    if placement is None:
        return row
    row.pop("placement", None)
    if placement.relation == "unknown":
        return row
    row["placement"] = {**placement.model_dump(), **proof}
    if placement.target_kind == "character":
        row["placement"]["target_origin"] = _origin(known[placement.target])
    return row


def invalidate_relations(actors: dict, moved: set[str], explicit_placements: set[str]) -> set[str]:
    """A new actor position/pose cannot silently preserve another actor's old relation."""
    invalidated = set()
    for actor_id, row in actors.items():
        placement = row.get("placement", {})
        if (
            actor_id not in explicit_placements
            and placement.get("target_kind") == "character"
            and placement.get("target") in moved
        ):
            row.pop("placement", None)
            invalidated.add(actor_id)
    return invalidated


def project(
    state: Any,
    cast: list[dict],
    *,
    scene_objects: dict[str, str | None] | None = None,
    target_ids: bool = False,
) -> dict[str, dict]:
    if not read_settings(state).scene_staging:
        return {}
    actors = retained(state, cast, scene_objects)
    return {key: _project_actor(row, target_ids=target_ids) for key, row in actors.items()}


def _project_actor(row: dict, *, target_ids: bool = False) -> dict:
    result: dict[str, Any] = {}
    try:
        if row.get("posture"):
            result["posture"] = _POSTURE.validate_python(row["posture"]["value"])
        if row.get("placement"):
            value = Placement.model_validate(
                {key: row["placement"][key] for key in ("relation", "target_kind", "target")}
            )
            result["placement"] = value.model_dump()
            if (
                target_ids
                and value.target_kind == "scene_object"
                and "target_id" in row["placement"]
            ):
                result["placement"]["target"] = row["placement"]["target_id"]
    except (KeyError, TypeError, ValidationError):
        return {}  # A corrupt legacy actor is unknown without hiding other actors.
    return result


def position(row: dict) -> dict:
    """Use known prop identity; legacy labels cannot masquerade as proven IDs."""
    position = _project_actor(row)
    placement = position.get("placement")
    if not placement or placement["target_kind"] != "scene_object":
        return position
    identifier = row["placement"].get("target_id")
    placement["target"] = (
        ("id", identifier)
        if isinstance(identifier, str) and identifier
        else ("label", placement["target"])
    )
    return position


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
    facts = project(state, cast, scene_objects=placement_targets(avatar, entities, state))
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
