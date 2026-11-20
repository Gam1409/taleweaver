"""Preserve only pose fields already applied by the current host command owner."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from backend.engine.npc_actions.reconciliation import context as command_context
from backend.engine.scene_staging.commands import CommandProof
from backend.engine.scene_staging.room_items import placement_targets
from backend.engine.scene_staging.schema import SceneExtraction
from backend.engine.scene_staging.state import KEY, _object_unavailable, project, retained

FIELDS = frozenset({"posture", "placement"})
INSTRUCTIONS = """
command_owned_fields identifies pose/placement fields already applied by the host
in this turn. Leave those fields unchanged; do not reconstruct, clear or repeat
them from prose. The current saved value, including an explicitly cleared value,
is authoritative. Separately resolved external_pose_sources may supersede those
fields through the staging owner. Other actors and unlisted fields remain eligible
under their source checks. This does not freeze clothing, body conditions, emotion
or environment.
"""


@dataclass(frozen=True)
class ProtectedActor:
    fields: dict[str, dict | None]
    origin: str
    command: dict


def _fields(control: dict) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for actor, outcomes in control["outcomes"].items():
        effects = [
            outcome["effect"]
            for outcome in outcomes
            if outcome.get("status") == "applied"
            and outcome.get("tool") in {"set_pose", "approach"}
            and isinstance(outcome.get("effect"), dict)
        ]
        result[actor] = set().union(*(FIELDS.intersection(effect) for effect in effects))
    return result


def _present(state: Any, actor: str) -> bool:
    row = (state.entity_states or {}).get(actor, {})
    return (
        isinstance(row, dict)
        and row.get("current_scene_id", state.current_scene_id) == state.current_scene_id
        and not (row.get("is_hidden") or row.get("is_defeated") or row.get("presence") == "absent")
    )


def _bound(source: Any, actor: str, scene: str, input_id: str) -> bool:
    return isinstance(source, dict) and (
        source.get("source_kind"),
        source.get("source_message_id"),
        source.get("command_actor_id"),
        source.get("command_scene_id"),
    ) == ("command", input_id, actor, scene)


def _row(
    state: Any,
    raw: dict,
    cast: list[dict] | None,
    actor: str,
    scene_objects: dict[str, str | None] | None,
) -> dict:
    if cast is not None:
        row: dict = retained(state, cast, scene_objects).get(actor, {})
        return row
    row = deepcopy(raw)
    placement = row.get("placement", {})
    if not isinstance(placement, dict):
        row.pop("placement", None)
        return row
    if placement.get("target_kind") == "scene_object" and _object_unavailable(
        state, placement.get("target_id")
    ):
        row.pop("placement", None)
    if placement.get("target_kind") == "character" and not _present(
        state, placement.get("target", "")
    ):
        row.pop("placement", None)
    return row


def capture(
    manager: Any,
    cast: list[dict] | None = None,
    *,
    scene_objects: dict[str, str | None] | None = None,
) -> dict[str, ProtectedActor]:
    control = command_context(manager)
    data = (manager.state.entity_states or {}).get(KEY)
    if (
        not control
        or not isinstance(data, dict)
        or data.get("scene_id") != manager.state.current_scene_id
        or data.get("status") != "ready"
    ):
        return {}
    current = data.get("actors", {})
    if not isinstance(current, dict):
        return {}
    fields = _fields(control)
    result = {}
    for actor, names in fields.items():
        raw = current.get(actor)
        if (
            not isinstance(raw, dict)
            or not _present(manager.state, actor)
            or not _bound(
                raw.get("command"),
                actor,
                manager.state.current_scene_id,
                manager._vn_player_message_id,
            )
        ):
            continue
        row = _row(manager.state, raw, cast, actor, scene_objects)
        if not row:
            continue
        facts = {
            name: deepcopy(row.get(name))
            for name in names
            if name not in row
            or _bound(
                row[name], actor, manager.state.current_scene_id, manager._vn_player_message_id
            )
        }
        if facts:
            result[actor] = ProtectedActor(
                facts, str(row.get("origin") or ""), deepcopy(row["command"])
            )
    return result


def metadata(manager: Any, cast: list[dict] | None = None) -> dict:
    protected = capture(manager, cast)
    return (
        {
            "command_owned_fields": {
                actor: sorted(record.fields) for actor, record in protected.items()
            }
        }
        if protected
        else {}
    )


def filter_changes(
    extraction: SceneExtraction, protected: dict[str, ProtectedActor]
) -> SceneExtraction:
    changes = []
    for change in extraction.changes:
        owned = protected.get(change.entity_id)
        if owned is None:
            changes.append(change)
            continue
        values: dict[str, Any] = {name: None for name in owned.fields}
        if change.clear and owned.fields.keys() >= FIELDS:
            values["clear"] = False
        candidate = change.model_copy(update=values)
        if candidate.clear or candidate.posture is not None or candidate.placement is not None:
            changes.append(candidate)
    return extraction.model_copy(update={"changes": changes})


def excluding(
    protected: dict[str, ProtectedActor], external: dict[str, set[str]]
) -> dict[str, ProtectedActor]:
    """A separately resolved external consequence keeps its staging owner authority."""
    return {
        actor: ProtectedActor(fields, record.origin, record.command)
        for actor, record in protected.items()
        if (
            fields := {
                name: value
                for name, value in record.fields.items()
                if name not in external.get(actor, set())
            }
        )
    }


def restore(result: dict, protected: dict[str, ProtectedActor]) -> dict:
    if not protected:
        return result
    value = deepcopy(result)
    actors = value.setdefault("actors", {})
    for actor, record in protected.items():
        row = actors.setdefault(actor, {"origin": record.origin})
        for name, fact in record.fields.items():
            if name == "placement" and actor in value.get("invalidated_placements", ()):
                continue
            if fact is None:
                row.pop(name, None)
            else:
                row[name] = deepcopy(fact)
        row["command"] = deepcopy(record.command)
    value["status"] = "ready"
    value["command_protected_fields"] = {
        actor: sorted(record.fields) for actor, record in protected.items()
    }
    return value


def _command_fact(source: Any, actor: str, scene: str) -> bool:
    if not isinstance(source, dict) or source.get("source_kind") != "command":
        return False
    try:
        proof = CommandProof.model_validate(
            {
                "command_id": source.get("command_id"),
                "actor_id": source.get("command_actor_id"),
                "scene_id": source.get("command_scene_id"),
                "input_id": source.get("source_message_id"),
                "input_revision": source.get("source_revision_id"),
                "request_hash": source.get("source_hash"),
                "operation": source.get("command_operation"),
            }
        )
    except ValidationError:
        return False
    return (proof.actor_id, proof.scene_id) == (actor, scene)


def _carry_commands(
    state: Any, result: dict, cast: list[dict], objects: dict[str, str | None] | None
) -> dict:
    valid = project(state, cast, scene_objects=objects)
    actors = {}
    for actor, row in retained(state, cast, objects).items():
        facts = {
            name: deepcopy(row[name])
            for name in FIELDS.intersection(valid.get(actor, {}))
            if _command_fact(row.get(name), actor, state.current_scene_id)
        }
        if not facts:
            continue
        actors[actor] = {"origin": row.get("origin", ""), **facts}
        if _command_fact(row.get("command"), actor, state.current_scene_id):
            actors[actor]["command"] = deepcopy(row["command"])
    if not actors:
        return result
    return {**result, "actors": actors, "status": "ready"}


def preserve(
    manager: Any, result: dict, cast: list[dict] | None = None, rows: list[Any] | None = None
) -> dict:
    """Failed extraction preserves retained command facts without locking future updates."""
    objects = (
        placement_targets(manager.avatar, rows, manager.state)
        if rows is not None and cast is not None
        else None
    )
    carried = _carry_commands(manager.state, result, cast, objects) if cast is not None else result
    return restore(carried, capture(manager, cast, scene_objects=objects))
