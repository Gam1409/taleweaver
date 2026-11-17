"""Preserve only pose fields already applied by the current host command owner."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from backend.engine.npc_actions.reconciliation import context as command_context
from backend.engine.scene_staging.schema import SceneExtraction
from backend.engine.scene_staging.state import KEY, _object_unavailable, retained

FIELDS = frozenset({"posture", "placement"})
INSTRUCTIONS = """
command_owned_fields identifies pose/placement fields already applied by the host
in this turn. Leave those fields unchanged; do not reconstruct, clear or repeat
them from prose. The current saved value, including an explicitly cleared value,
is authoritative. Other actors and unlisted fields remain eligible for supported
changes. This does not freeze clothing, body conditions, emotion or environment.
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


def _row(state: Any, raw: dict, cast: list[dict] | None, actor: str) -> dict:
    if cast is not None:
        row: dict = retained(state, cast).get(actor, {})
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


def capture(manager: Any, cast: list[dict] | None = None) -> dict[str, ProtectedActor]:
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
        row = _row(manager.state, raw, cast, actor)
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


def restore(result: dict, protected: dict[str, ProtectedActor]) -> dict:
    if not protected:
        return result
    value = deepcopy(result)
    actors = value.setdefault("actors", {})
    for actor, record in protected.items():
        row = actors.setdefault(actor, {"origin": record.origin})
        for name, fact in record.fields.items():
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


def preserve(manager: Any, result: dict) -> dict:
    """A failed extractor can unconfirm unrelated staging, never an applied command."""
    return restore(result, capture(manager))
