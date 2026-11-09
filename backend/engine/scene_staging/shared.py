"""Reuse staging validation/state in the existing completed-turn extraction request."""

import logging
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from backend.core.reliability_metrics import record_staging
from backend.engine.clothing.context import actor_records
from backend.engine.visual_novel.config import read_settings
from backend.engine.visual_novel.continuity import PLAYER

from . import bindings, props
from .schema import SceneExtraction
from .state import KEY, digest, project, reconcile

logger = logging.getLogger(__name__)


@dataclass
class Pending:
    scene_id: str
    source_hash: str
    before: Any
    before_props: Any
    cast: list[dict] = field(default_factory=list)
    rows: list[Any] = field(default_factory=list)
    extraction: Any = None
    accepted: list[dict] = field(default_factory=list)
    error: str = "The shared state extraction did not complete."


def begin(manager: Any, narration: str) -> bool:
    manager._shared_scene_staging = None
    if not read_settings(manager.state).scene_staging:
        return False
    states = manager.state.entity_states or {}
    manager._shared_scene_staging = Pending(
        manager.state.current_scene_id,
        digest(narration),
        deepcopy(states.get(KEY)),
        deepcopy(states.get(props.KEY)),
    )
    return True


def _cast(manager: Any, actors: dict, rows: list[Any]) -> list[dict]:
    by_id = {row.id: row for row in rows}
    states = manager.state.entity_states or {}
    return [
        {
            "id": bindings.actor_id(identifier, manager.avatar.id),
            "name": actor["name"],
            "position": (states.get(identifier) or {}).get(
                "spatial_position", getattr(by_id.get(identifier), "spatial_position", None)
            ),
        }
        for identifier, actor in actors.items()
    ]


def prepare(manager: Any, actors: dict, rows: list[Any]) -> dict | None:
    pending = getattr(manager, "_shared_scene_staging", None)
    if not isinstance(pending, Pending):
        return None
    pending.rows, pending.cast = rows, _cast(manager, actors, rows)
    people, previous = bindings.input_cast(
        pending.cast, project(manager.state, pending.cast), manager.avatar.id
    )
    items = props.candidates(
        manager.avatar,
        rows,
        manager.state,
        {person["id"] for person in pending.cast},
        include_worn=True,
    )
    return {
        "scene_id": pending.scene_id,
        "present_cast": people,
        "previous_staging": previous,
        "owned_items": [
            {
                "item_id": item["item_id"],
                "owner_id": PLAYER if item["owner_id"] == manager.avatar.id else item["owner_id"],
            }
            for item in items
        ],
    }


def complete(manager: Any, extraction: Any, accepted: list[dict]) -> None:
    pending = getattr(manager, "_shared_scene_staging", None)
    if isinstance(pending, Pending):
        pending.extraction, pending.accepted = deepcopy(extraction), deepcopy(accepted)
        pending.error = (
            "" if extraction is not None else "The shared response did not confirm staging."
        )


def propose(manager: Any, response: Any) -> None:
    """A malformed item section must not veto an independently valid pose section."""
    raw = response.model_dump() if isinstance(response, BaseModel) else response
    complete(manager, raw.get("staging") if isinstance(raw, dict) else None, [])


def approve_items(manager: Any, accepted: list[dict]) -> None:
    pending = getattr(manager, "_shared_scene_staging", None)
    if isinstance(pending, Pending):
        pending.accepted = deepcopy(accepted)


def invalidate(state: Any, narration: str, reason: str) -> None:
    props.invalidate(state)
    state.entity_states = {
        **(state.entity_states or {}),
        KEY: {
            "scene_id": state.current_scene_id,
            "status": "unconfirmed",
            "source_hash": digest(narration),
            "reason": reason,
            "actors": {},
        },
    }


def apply_extraction(
    manager: Any,
    narration: str,
    cast: list[dict],
    rows: list[Any],
    extraction: SceneExtraction,
    accepted: list[dict] | None = None,
) -> None:
    extraction, rejected = bindings.resolve(extraction, manager.avatar.id, accepted or [])
    result = reconcile(manager.state, cast, narration, extraction)
    result["rejected_prop_references"] = rejected
    record_staging(result, len(extraction.changes))
    valid = props.candidates(
        manager.avatar, rows, manager.state, {row.id for row in rows if row.entity_type == "NPC"}
    )
    present = {person["id"] for person in cast}
    result["rejected_props"] = rejected + props.reconcile(
        manager.state,
        narration,
        extraction.props,
        [item for item in valid if item["owner_id"] in present],
        valid_items=valid,
    )
    if result["status"] != "ready":
        props.invalidate(manager.state)
    manager.state.entity_states = {**(manager.state.entity_states or {}), KEY: result}


def consume(manager: Any, narration: str, *, completed: bool) -> bool:
    pending = getattr(manager, "_shared_scene_staging", None)
    manager._shared_scene_staging = None
    if not isinstance(pending, Pending):
        return False
    states = manager.state.entity_states or {}
    if states.get(KEY) != pending.before or states.get(props.KEY) != pending.before_props:
        logger.warning(
            "Ignoring stale shared staging result for session %s", manager.state.session_id
        )
        return True
    if (
        not completed
        or pending.scene_id != manager.state.current_scene_id
        or pending.source_hash != digest(narration)
    ):
        invalidate(manager.state, narration, "The shared staging source no longer matches.")
        return True
    if pending.error:
        invalidate(manager.state, narration, pending.error)
        return True
    try:
        current_cast = _cast(manager, actor_records(manager, pending.rows), pending.rows)
        if current_cast != pending.cast:
            raise ValueError("The present cast or its position changed during extraction.")
        extraction = SceneExtraction.model_validate(pending.extraction)
        apply_extraction(
            manager, narration, current_cast, pending.rows, extraction, pending.accepted
        )
    except Exception:
        logger.exception("Shared scene staging failed for session %s", manager.state.session_id)
        invalidate(manager.state, narration, "The shared staging response could not be confirmed.")
    return True
