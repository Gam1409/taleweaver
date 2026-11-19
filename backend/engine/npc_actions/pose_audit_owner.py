"""Read current public pose facts and preview the existing staging owner on copies."""

from copy import copy
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from backend.engine.actor_aliases import public_actor_id
from backend.engine.npc_actions import execution_frame
from backend.engine.scene_staging.state import KEY, _project_actor, digest, retained
from backend.engine.visual_novel.config import read_settings
from backend.engine.visual_novel.continuity import SCENE


@dataclass(frozen=True)
class Preview:
    facts: dict[str, dict]
    external: dict[str, set[str]]
    rejected: tuple[Any, ...] = ()


def external_fields(manager: Any, narration: str) -> dict[str, set[str]]:
    turn = manager._chpm_turn
    actors = (manager.state.entity_states or {}).get(KEY, {}).get("actors", {})
    return {
        actor: {
            name
            for name in ("posture", "placement")
            if isinstance(fact := row.get(name), dict)
            and fact.get("source_kind") == "external_effect"
            and fact.get("source_hash") == digest(narration)
            and (cause := fact.get("cause", {})).get("source_message_id") == turn.input_id
            and cause.get("source_revision_id") == turn.control.get("input_revision")
            and cause.get("source_hash") == turn.control.get("input_hash")
        }
        for actor, row in actors.items()
        if actor in turn.decisions and isinstance(row, dict)
    }


def targets(turn: Any) -> dict[str, str]:
    frame = getattr(turn, "execution_frame", None)
    if not isinstance(frame, execution_frame.Frame):
        return {}
    return {
        key: row["kind"]
        for key, row in frame.entities.items()
        if row.get("kind") == "actor" or row.get("kind") == "item" and row.get("owner_id") == SCENE
    }


def facts(manager: Any, actors: dict, rows: list[Any]) -> dict[str, dict]:
    from backend.engine.scene_staging import shared

    turn = manager._chpm_turn
    public = targets(turn)
    saved = retained(manager.state, shared._cast(manager, actors, rows))
    result = {}
    for actor in turn.decisions:
        if actor not in public:
            continue
        original = saved.get(actor, {})
        current = _project_actor(original)
        placement = current.pop("placement", None)
        if placement:
            bound = original["placement"]
            target = (
                bound.get("target_id")
                if placement["target_kind"] == "scene_object"
                else public_actor_id(placement["target"], player_id=manager.avatar.id)
            )
            if target in public:
                current["placement"] = {**placement, "target": target}
        result[actor] = current
    return result


def preview(manager: Any, narration: str, staging: Any, actors: dict, rows: list[Any]) -> Preview:
    from backend.engine.scene_staging import attribution, bindings, shared
    from backend.engine.scene_staging.proposals import validate

    current = facts(manager, actors, rows)
    if staging is None:
        return Preview(current, {})
    cast = shared._cast(manager, actors, rows)
    validated = validate(staging)
    changes, _ = bindings.resolve(validated.value, manager.avatar.id, [])
    pending = getattr(manager, "_shared_scene_staging", None)
    _, _, external, denied = attribution.admit(
        manager, changes, cast, narration, getattr(pending, "authority", None)
    )
    refused = {row["actor_id"] for row in denied}
    rejected = tuple(
        change
        for change in changes.changes
        if change.entity_id in refused
        and attribution._new_fields(change, current.get(change.entity_id, {}))
    )
    if not external or not read_settings(manager.state).scene_staging:
        return Preview(current, {}, rejected)
    state = manager.state
    probe = copy(manager)
    probe.state = SimpleNamespace(
        **{
            name: getattr(state, name, None)
            for name in (
                "session_id",
                "current_scene_id",
                "in_game_time",
                "entity_states",
                "exit_states",
                "inventory",
                "quests",
            )
        }
    )
    # Staging/props owners copy their own records before replacing their keys.
    # Large notebook, knowledge and history values are read-only shared references.
    probe.state.entity_states = dict(state.entity_states or {})
    probe._npc_narration_fence = None
    shared.apply_extraction(
        probe,
        narration,
        cast,
        rows,
        staging,
        authority=getattr(pending, "authority", None),
        audit=False,
    )
    return Preview(facts(probe, actors, rows), external_fields(probe, narration), rejected)
