"""Read confirmed staging for a present observer without granting new world facts."""

from typing import Any

from pydantic import ValidationError

from backend.engine.chpm.host_observation_contracts import CharacterPose, PlacedItem
from backend.engine.scene_staging import props
from backend.engine.scene_staging.state import KEY, project, registry
from backend.engine.visual_novel.config import read_settings


def observations(
    state: Any, cast: list[dict], items: list[dict], observer_id: str, player_id: str
) -> tuple[tuple[CharacterPose, ...] | None, tuple[PlacedItem, ...] | None, dict | None]:
    if not read_settings(state).scene_staging:
        return None, None, None
    data = registry(state)
    poses = None
    if (
        KEY in (state.entity_states or {})
        and data.get("status") == "ready"
        and data.get("scene_id") == state.current_scene_id
    ):
        poses = _poses(state, cast, player_id)
    placed = None
    if props.KEY in (state.entity_states or {}):
        placed = _items(state, items, observer_id, player_id)
    omitted = {}
    for key, rows, limit in (("character_poses", poses, 128), ("placed_items", placed, 256)):
        if rows is not None and len(rows) > limit:
            omitted[key] = len(rows) - limit
    return (
        poses[:128] if poses is not None else None,
        placed[:256] if placed is not None else None,
        omitted or None,
    )


def _poses(state: Any, cast: list[dict], player_id: str) -> tuple[CharacterPose, ...] | None:
    result = []
    try:
        projected = project(state, cast)
    except (KeyError, TypeError, ValueError):
        return None
    for actor_id, raw in sorted(projected.items()):
        if not raw:
            continue
        row = {**raw, "entity_id": _actor_id(actor_id, player_id)}
        placement = row.get("placement")
        if placement and placement.get("target_kind") == "character":
            row["placement"] = {**placement, "target": _actor_id(placement["target"], player_id)}
        try:
            result.append(CharacterPose.model_validate(row))
        except ValidationError:
            continue  # Malformed legacy facts stay unknown, never a guessed pose.
    return tuple(result)


def _items(
    state: Any, items: list[dict], observer_id: str, player_id: str
) -> tuple[PlacedItem, ...]:
    result = []
    for row in props.project(state, items, observer_id=observer_id):
        try:
            result.append(
                PlacedItem.model_validate(
                    {
                        **row,
                        "owner_id": _actor_id(row["owner_id"], player_id),
                        "name": row["name"][:160] if isinstance(row["name"], str) else row["name"],
                    }
                )
            )
        except ValidationError:
            continue
    return tuple(result)


def _actor_id(identifier: str, player_id: str) -> str:
    return "@player" if identifier == player_id else identifier
