"""Transient observer-scoped views of existing state owners, never another world store."""

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from backend.engine.actor_aliases import public_actor_id, public_placement
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.schema import Observation
from backend.engine.clothing.context import actor_records
from backend.engine.clothing.projection import item_wear_state, visible_character
from backend.engine.clothing.visuals import detailed_for_state, session_objects
from backend.engine.physical_conditions.ledger import read
from backend.engine.physical_conditions.schema import Ledger
from backend.engine.physical_conditions.scope import item_scope
from backend.engine.physical_conditions.visuals import project as visible_conditions
from backend.engine.scene_staging import props
from backend.engine.visual_novel.continuity import PLAYER, SCENE, possession_snapshot


@dataclass(frozen=True)
class View:
    session_id: str
    observer_id: str
    message_id: str
    revision_id: str | None
    content_hash: str
    scene_id: str
    entities: dict[str, dict]
    scene: dict = field(default_factory=dict)


def _ledger(state: Any) -> Ledger | None:
    try:
        ledger = read(state.entity_states)
    except ValueError:
        return None
    return ledger if ledger.revision or ledger.conditions else None


def _conditions(ledger: Ledger | None, target: str, *, own: bool, visible: set[str]) -> list[dict]:
    rows = (
        sorted(
            (row for row in ledger.conditions.values() if row.target_id == target),
            key=lambda row: (row.status == "resolved", -row.updated_revision, row.id),
        )
        if ledger
        else []
    )
    return [
        {
            "id": row.id,
            "kind": row.kind,
            "part": row.part,
            "status": row.status,
            **(
                {
                    "detail": row.detail
                    if own or row.kind == "item_state" and row.latest.kind == "command"
                    else row.visual_detail
                }
                if row.status != "resolved"
                else {}
            ),
        }
        for row in rows
        if own or row.id in visible
    ]


def _profile_view(actor: dict, detailed: bool) -> dict | None:
    return visible_character(
        actor.get("visual_profile"),
        actor.get("resolved_inventory") or [],
        detailed=detailed,
        equipment=actor.get("equipment"),
    )


def _wear_state(actor: dict, item_id: str) -> str:
    return item_wear_state(
        actor.get("visual_profile"),
        actor.get("resolved_inventory"),
        item_id,
        equipment=actor.get("equipment"),
    )


def _actor_view(identifier: str, actor: dict, visual: dict | None, conditions: list[dict]) -> dict:
    return {
        "id": public_actor_id(identifier),
        "name": str(actor.get("name") or "")[:160],
        "kind": "actor",
        "visible_clothing": deepcopy(visual["clothing"]) if visual else None,
        "clothing_knowledge": "visible_layers_only" if visual and visual["clothing"] else "unknown",
        "recorded_conditions": conditions,
    }


def _item_view(identifier: str, item: dict, owner: str, wear: str, conditions: list[dict]) -> dict:
    return {
        "id": identifier,
        "name": str(item.get("name") or "")[:160],
        "kind": "item",
        "owner_id": public_actor_id(owner),
        "worn_by": public_actor_id(owner) if wear == "worn" else None,
        "wear_status": "not_worn" if wear == "carried" else wear,
        "recorded_conditions": conditions,
        **(
            {"spatial_position": item["spatial_position"]}
            if owner == SCENE and item.get("spatial_position")
            else {}
        ),
    }


def project(
    manager: Any,
    rows: list[Any],
    observer_id: str,
    observation: Observation,
    *,
    own_facts: bool = True,
) -> View:
    """Own facts plus public surfaces; no arbitrary metadata, bags or private other minds."""
    state = manager.state
    if (
        manager.game_id != observation.session_id
        or getattr(state, "session_id", manager.game_id) != observation.session_id
        or state.current_scene_id != observation.scene_id
    ):
        raise ChpmError("Observable state belongs to another session or scene.")
    rows = [
        row
        for row in rows
        if getattr(row, "session_id", manager.game_id) in {None, manager.game_id}
    ]
    actors = actor_records(manager, rows)
    if observer_id not in actors:
        raise ChpmError("The state observer is not present.")
    snapshot = possession_snapshot(manager, rows)
    scope = item_scope(manager, rows, snapshot=snapshot)
    detailed = detailed_for_state(state)
    ledger = _ledger(state)
    visible = {
        row["id"] for row in visible_conditions(state, actors, detailed=detailed, limit=None)
    }
    visuals = {key: _profile_view(actor, detailed) for key, actor in actors.items()}
    for owner, visual in visuals.items():
        if visual:
            visual["clothing"] = [
                item for item in visual["clothing"] if snapshot.owners.get(item["item_id"]) == owner
            ]
    own = {key for key, owner in snapshot.owners.items() if owner == observer_id and own_facts}
    entities = {
        public_actor_id(key): _actor_view(
            key,
            actor,
            visuals[key],
            _conditions(ledger, key, own=own_facts and key == observer_id, visible=visible),
        )
        for key, actor in actors.items()
    }
    _add_poses(manager, rows, actors, entities)
    available: dict[str, str] = {
        key: SCENE for key in scope.public_ids if snapshot.owners.get(key, SCENE) == SCENE
    }
    available.update({key: observer_id for key in own})
    _add_worn(available, visuals, snapshot.owners)
    placed = props.project(
        state,
        props.candidates(manager.avatar, rows, state, set(actors) - {PLAYER}),
        observer_id=observer_id,
    )
    placed = [
        {**row, "owner_id": PLAYER if row["owner_id"] == manager.avatar.id else row["owner_id"]}
        for row in placed
    ]
    available.update(
        {row["item_id"]: snapshot.owners.get(row["item_id"], row["owner_id"]) for row in placed}
    )
    loose = {key for key in available if available[key] == SCENE} | {
        row["item_id"] for row in placed
    }
    _add_items(entities, available, snapshot, actors, ledger, visible, own, loose)
    for row in placed:
        if row["item_id"] in entities:
            entities[row["item_id"]]["spatial_position"] = row["spatial_position"]
    return View(
        observation.session_id,
        observer_id,
        observation.message_id,
        observation.revision_id,
        observation.content_hash,
        observation.scene_id,
        entities,
    )


def _add_poses(manager: Any, rows: list, actors: dict, entities: dict) -> None:
    from backend.engine.scene_staging.shared import _cast
    from backend.engine.scene_staging.state import project as poses

    try:
        current = poses(manager.state, _cast(manager, actors, rows))
    except (KeyError, TypeError, ValueError):
        return
    for identifier, pose in current.items():
        actor = public_actor_id(identifier, player_id=manager.avatar.id)
        if actor not in entities:
            continue
        public = dict(pose)
        placement = pose.get("placement")
        if placement:
            public["placement"] = public_placement(placement, player_id=manager.avatar.id)
        entities[actor].update(public)


def _add_worn(available: dict[str, str], visuals: dict[str, dict | None], owners: dict) -> None:
    worn = (
        (item["item_id"], owner)
        for owner, visual in visuals.items()
        if visual
        for item in visual["clothing"]
        if owners.get(item["item_id"]) == owner
    )
    for identifier, owner in worn:
        available.setdefault(identifier, owner)


def _add_items(
    entities: dict,
    available: dict,
    snapshot: Any,
    actors: dict,
    ledger: Ledger | None,
    visible: set[str],
    own: set[str],
    loose: set[str],
) -> None:
    for identifier, owner in available.items():
        item = snapshot.catalog.get(identifier) or snapshot.items.get(identifier)
        if item is None:
            continue
        owned = identifier in own
        # Public loose objects have an explicit visual excerpt but no clothing region.
        surfaces = (
            visible
            | {
                row.id
                for row in ledger.conditions.values()
                if row.target_id == identifier
                and identifier in loose
                and row.visibility == "public"
                and row.status != "resolved"
                and (row.visual_detail or row.kind == "item_state" and row.latest.kind == "command")
                and row.latest.kind != "unavailable"
            }
            if ledger
            else visible
        )
        wear = _wear_state(actors[owner], identifier) if owner in actors else "carried"
        entities[identifier] = _item_view(
            identifier,
            item,
            owner,
            wear,
            _conditions(ledger, identifier, own=owned, visible=surfaces),
        )
        entities[identifier]["condition_knowledge"] = "recorded_only" if ledger else "unavailable"


async def capture(
    manager: Any, observer_ids: list[str], observation: Observation
) -> dict[str, View]:
    from dataclasses import replace

    from backend.engine.chpm import observable_scene

    rows = await session_objects(manager.db, manager.game_id)
    routes = await observable_scene.capture(manager, rows)
    return {
        key: replace(
            project(manager, rows, key, observation),
            scene=observable_scene.project(manager, routes, key),
        )
        for key in observer_ids
    }
