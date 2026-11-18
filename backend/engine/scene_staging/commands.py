"""Apply host-issued local pose commands without inventing narrated evidence."""

from copy import deepcopy
from types import SimpleNamespace
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from backend.engine.scene_staging.schema import Placement, Posture
from backend.engine.scene_staging.state import (
    KEY,
    _project_actor,
    apply_fields,
    invalidate_relations,
    retained,
)

_POSTURE: TypeAdapter[Posture] = TypeAdapter(Posture)


def _position(row: dict) -> dict:
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


class CommandProof(BaseModel):
    """Host metadata bound to the real input; it is not an LLM function argument."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, str_strip_whitespace=True)

    command_id: str = Field(min_length=1, max_length=100)
    actor_id: str = Field(min_length=1, max_length=100)
    scene_id: str = Field(min_length=1, max_length=100)
    input_id: str = Field(min_length=1, max_length=100)
    input_revision: str | None = Field(default=None, max_length=100)
    request_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    operation: Literal["set_pose", "approach"]


def _previous(states: dict) -> dict:
    raw = states.get(KEY)
    if raw is None:
        return {}
    if not isinstance(raw, dict) or not isinstance(raw.get("actors", {}), dict):
        raise ValueError("Stored scene staging requires repair before a pose command.")
    if any(
        key in raw and not isinstance(raw[key], list) for key in ("explicit", "unconfirmed_actors")
    ):
        raise ValueError("Stored scene staging lists require repair before a pose command.")
    if any(
        not isinstance(entry, dict) or not isinstance(entry.get("participants", []), list)
        for entry in raw.get("explicit", [])
    ):
        raise ValueError("Stored scene staging activities require repair before a pose command.")
    rows = raw.get("actors", {})
    for row in rows.values():
        if not isinstance(row, dict) or any(
            key in row and not isinstance(row[key], dict)
            for key in ("posture", "placement", "command")
        ):
            raise ValueError(
                "Stored scene staging actor facts require repair before a pose command."
            )
    return deepcopy(raw)


def _placement(
    placement: Placement | None, *, actor_id: str, known: dict, objects: dict[str, str]
) -> tuple[Placement | None, str | None]:
    if placement is None:
        return None, None
    selected = Placement.model_validate(placement.model_dump())
    if selected.target_kind == "character":
        if selected.target not in known or selected.target == actor_id:
            raise ValueError("The placement target is not another present character.")
        return selected, None
    name = objects.get(selected.target)
    if not isinstance(name, str) or not name.strip() or len(name) > 120:
        raise ValueError("The placement target is not a known observable scene object.")
    return selected.model_copy(update={"target": name}), selected.target


def _record(proof: CommandProof) -> dict[str, Any]:
    return {
        "source_kind": "command",
        "command_id": proof.command_id,
        "command_operation": proof.operation,
        "command_actor_id": proof.actor_id,
        "command_scene_id": proof.scene_id,
        "source_message_id": proof.input_id,
        "source_revision_id": proof.input_revision,
        "source_hash": proof.request_hash,
    }


def _validate(
    proof: CommandProof,
    *,
    actor_id: str,
    scene_id: str,
    known: dict,
    posture: Posture | None,
    placement: Placement | None,
    enabled: bool,
) -> None:
    if enabled is not True:
        raise ValueError("Scene staging is disabled.")
    if (proof.actor_id, proof.scene_id) != (actor_id, scene_id) or actor_id not in known:
        raise ValueError("The pose command scope no longer matches its present actor and scene.")
    if posture is None and placement is None:
        raise ValueError("A pose command requires a final posture or placement.")
    if proof.operation == "set_pose" and posture is None:
        raise ValueError("set_pose requires a final posture.")
    if proof.operation == "approach" and (
        placement is None or placement.relation not in {"near", "beside", "in_front_of", "behind"}
    ):
        raise ValueError("approach requires a local relation to a present target.")


def apply_command(
    states: dict,
    *,
    scene_id: str,
    cast: list[dict],
    actor_id: str,
    proof: CommandProof,
    enabled: bool,
    posture: Posture | None = None,
    placement: Placement | None = None,
    scene_objects: dict[str, str] | None = None,
) -> dict:
    """Return owner state only; caller rechecks input/controller freshness before publication."""
    proof = CommandProof.model_validate(proof.model_dump())
    posture = _POSTURE.validate_python(posture) if posture is not None else None
    known = {person["id"]: person for person in cast}
    _validate(
        proof,
        actor_id=actor_id,
        scene_id=scene_id,
        known=known,
        posture=posture,
        placement=placement,
        enabled=enabled,
    )
    selected, target_id = _placement(
        placement, actor_id=actor_id, known=known, objects=scene_objects or {}
    )
    data = _previous(states)
    if data.get("scene_id") != scene_id:
        data = {}
    actors = retained(SimpleNamespace(entity_states=states, current_scene_id=scene_id), cast)
    source = _record(proof)
    command = {
        **source,
        "requested_posture": posture,
        "requested_placement": placement.model_dump() if placement else None,
    }
    row = actors.get(actor_id, {})
    previous = row.get("command", {})
    if previous.get("command_id") == proof.command_id:
        if previous != command:
            raise ValueError("A pose command identity cannot be reused for a different request.")
        return deepcopy(states)
    previous_position = _position(row)
    actors[actor_id] = apply_fields(
        row, actor_id=actor_id, posture=posture, placement=selected, known=known, proof=source
    )
    actors[actor_id]["command"] = command
    if target_id is not None:
        actors[actor_id]["placement"]["target_id"] = target_id
    # Re-stamping a command proves the same position again; only a changed
    # final public pose or placement invalidates another actor's relation.
    moved = _position(actors[actor_id]) != previous_position
    invalidate_relations(actors, {actor_id} if moved else set(), {actor_id} if selected else set())
    return _finish(states, data, actors, actor_id, scene_id)


def _finish(states: dict, data: dict, actors: dict, actor_id: str, scene_id: str) -> dict:
    data.update(scene_id=scene_id, status="ready", actors=actors)
    data["unconfirmed_actors"] = [
        value for value in data.get("unconfirmed_actors", []) if value != actor_id
    ]
    data["explicit"] = [
        entry for entry in data.get("explicit", []) if actor_id not in entry.get("participants", [])
    ]
    result = deepcopy(states)
    result[KEY] = data
    return result
