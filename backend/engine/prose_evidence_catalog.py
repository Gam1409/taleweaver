"""Public identity candidates for prose evidence, from the scene the player saw."""

from types import SimpleNamespace
from typing import Any

from backend.engine.clothing.context import actor_records
from backend.engine.clothing.projection import visible_character
from backend.engine.clothing.visuals import detailed_for_state
from backend.engine.scene_staging.room_items import placement_targets
from backend.engine.visual_novel.continuity import PLAYER, possession_snapshot

Catalog = tuple[dict[str, str], dict[str, str]]


def catalog(
    before: dict, *, user_id: str, session_id: str, avatar_id: str | None
) -> Catalog | None:
    # Imported or older saves can lack a matching checkpoint. Never substitute the
    # current avatar, or use identities copied from a different user or session.
    if (
        not isinstance(before, dict)
        or before.get("version") != 1
        or before.get("user_id") != user_id
    ):
        return None
    try:
        avatar = SimpleNamespace(**before["avatar"])
        state = SimpleNamespace(**before["state"])
        if (
            state.session_id != session_id
            or getattr(state, "user_id", None) not in (None, user_id)
            or avatar.user_id != user_id
            or avatar.id != avatar_id
            or state.avatar_id != avatar_id
        ):
            return None
        rows = [SimpleNamespace(**row) for row in before["tables"]["world_entities"]]
        if any(row.session_id != session_id for row in rows):
            return None
        return visible_catalog(SimpleNamespace(avatar=avatar, state=state), rows)
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


def visible_catalog(manager: Any, rows: list[Any]) -> Catalog:
    state = manager.state
    owners = possession_snapshot(manager, rows)
    actors = actor_records(manager, rows)
    items = {
        key: name for key, name in placement_targets(manager.avatar, rows, state).items() if name
    }
    items.update(
        {key: owners.items[key]["name"] for key, owner in owners.owners.items() if owner == PLAYER}
    )
    detailed = detailed_for_state(state)
    for key, actor in actors.items():
        if key == PLAYER:
            continue
        visible = visible_character(
            actor["visual_profile"], actor["resolved_inventory"], detailed=detailed
        )
        for garment in (visible or {}).get("clothing", []):
            item_id = garment["item_id"]
            if garment["name"] and owners.owners.get(item_id) == key:
                items[item_id] = garment["name"]
    names = {key: owners.npcs[key]["name"] for key in actors if key in owners.npcs}
    return {PLAYER: manager.avatar.name or "Player", **names}, {
        key: name for key, name in items.items() if isinstance(name, str) and name.strip()
    }
