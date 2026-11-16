"""Resolve unambiguous actor labels without granting presence to absent actors."""

from backend.engine.narrated_items.schema import ItemAction
from backend.engine.visual_novel.continuity import SCENE


def resolve_participants(action: ItemAction, actors: dict) -> ItemAction:
    resolved = {}
    for field in ("source_owner", "destination_owner"):
        value = getattr(action, field)
        if value in actors or (field == "source_owner" and value == SCENE):
            resolved[field] = value
            continue
        matches = [
            identifier
            for identifier, actor in actors.items()
            if str(actor.get("name", "")).strip().casefold() == value.casefold()
        ]
        if len(matches) != 1:
            available = ", ".join(
                f"{actor.get('name') or identifier} [{identifier}]"
                for identifier, actor in actors.items()
            )
            reason = "ambiguous" if matches else "not present or not recognized"
            raise ValueError(f"{field} '{value}' is {reason}. Available participants: {available}.")
        resolved[field] = matches[0]
    return action.model_copy(update=resolved)
