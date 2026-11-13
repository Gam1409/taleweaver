"""Orient a stored exit without copying its authoritative locks or scripts."""

from sqlalchemy import and_, or_
from sqlalchemy.sql.elements import ColumnElement

from backend.models.world_entity import WorldExit


def traversal_destination(world_exit: WorldExit, current_scene_id: str) -> str | None:
    """Use the same directional contract as explicit player traversal."""
    if world_exit.from_scene_id.lower() == current_scene_id.lower():
        return world_exit.to_scene_id
    if (
        str(world_exit.exit_type or "").lower() == "bidirectional"
        and world_exit.to_scene_id.lower() == current_scene_id.lower()
    ):
        return world_exit.from_scene_id
    return None


def outgoing_condition(current_scene_id: str) -> ColumnElement[bool]:
    """Select canonical forward rows and incoming bidirectional rows only."""
    return or_(
        WorldExit.from_scene_id == current_scene_id,
        and_(WorldExit.to_scene_id == current_scene_id, WorldExit.exit_type == "bidirectional"),
    )
