"""World differences are witnessed host facts, never attributed intentions."""

import json
from typing import Any

from backend.engine.chpm import physical_observations
from backend.engine.chpm.host_observation_contracts import HostFacts, ObservedScene, Possession
from backend.engine.chpm.host_state import Mind
from backend.engine.clothing.profiles import load_profile, owned_items
from backend.engine.scene_continuity.npc import difference as scene_difference
from backend.engine.scene_continuity.npc import observations as scene_observations
from backend.engine.scene_staging.npc import observations as staging_observations


def capture(
    state: Any,
    actor: Any,
    present: dict[str, str],
    *,
    scene_targets: set[str] | None = None,
    scene_description: str | None = None,
    staging_cast: list[dict] | None = None,
    placed_items: list[dict] | None = None,
    player_id: str = "",
    last_observed_scene: ObservedScene | None = None,
) -> HostFacts:
    override = (state.entity_states or {}).get(actor.id) or {}
    metadata = getattr(actor, "metadata_json", None) or {}
    authored = getattr(actor, "inventory", None)
    inventory = override.get(
        "inventory", authored if authored is not None else metadata.get("inventory")
    )
    profile = load_profile(override.get("visual_profile", getattr(actor, "visual_profile", None)))
    possessions = owned_items(inventory)
    known_inventory = isinstance(inventory, (list, tuple, dict))
    poses, placed, staging_omissions = (
        staging_observations(state, staging_cast, placed_items or [], actor.id, player_id)
        if staging_cast is not None
        else (None, None, None)
    )
    return HostFacts(
        scene_id=state.current_scene_id,
        last_observed_scene=last_observed_scene,
        visible_actor_ids=tuple(sorted(set(present) - {actor.id})),
        owned_items=tuple(
            Possession(id=key, name=str(item.get("name") or "")[:160])
            for key, item in sorted(possessions.items())
        )
        if known_inventory
        else None,
        physical_conditions=physical_observations.capture(state, actor.id, set(possessions)),
        character_poses=poses,
        placed_items=placed,
        staging_omissions=staging_omissions,
        scene_facts=scene_observations(
            state,
            actor.id,
            scene_targets or {state.current_scene_id, actor.id, "__player__", *present},
            scene_description=scene_description,
        ),
        # Invalid/missing profiles are unknown, never proof of undressing.
        worn_item_ids=tuple(sorted(w.item_id for w in profile.worn))
        if profile and known_inventory and all(w.item_id in possessions for w in profile.worn)
        else None,
    )


def previous(mind: Mind) -> HostFacts | None:
    for evidence in reversed(mind.snapshot.evidence):
        source = mind.sources.get(evidence.event_id)
        if source and source.kind == "host_frame":
            return source.facts
    return None


def frame(facts: HostFacts) -> str:
    return _bounded({"observation": "current_host_state", **facts.model_dump(mode="json")})


def situation(mind: Mind) -> dict:
    facts = previous(mind)
    if facts is None:
        return {}
    observed = json.loads(frame(facts))
    # Other host facts may be observer-private. Their existing narration owners
    # decide what can be disclosed; this handoff contains only the public frame.
    moment = observed.get("last_observed_scene")
    return {"scene_id": facts.scene_id, "last_observed_scene": moment} if moment else {}


def remap_frame(source: Any, message_ids: dict[str, str]) -> Any:
    facts = source.facts
    moment = facts.last_observed_scene if facts else None
    if moment is None:
        return source
    changed = facts.model_copy(
        update={
            "last_observed_scene": ObservedScene.model_validate(
                {
                    **moment.model_dump(mode="json"),
                    "source_message_id": message_ids[moment.source_message_id],
                }
            )
        }
    )
    return source.model_copy(update={"facts": changed, "text": frame(changed)})


def difference(before: HostFacts | None, after: HostFacts) -> str | None:
    if before is None:
        return None
    changes: dict[str, Any] = {}
    if before.scene_id != after.scene_id:
        changes["own_scene_change"] = {"from": before.scene_id, "to": after.scene_id}
    else:
        # A new scene does not establish that other actors have moved.
        _sets(changes, "visible_actors", before.visible_actor_ids, after.visible_actor_ids)
    if before.owned_items is not None and after.owned_items is not None:
        old, new = {p.id: p for p in before.owned_items}, {p.id: p for p in after.owned_items}
        for label, keys, values in (
            ("own_items_gained", new.keys() - old.keys(), new),
            ("own_items_lost", old.keys() - new.keys(), old),
        ):
            if keys:
                changes[label] = [values[key].model_dump() for key in sorted(keys)]
    if before.worn_item_ids is not None and after.worn_item_ids is not None:
        _sets(changes, "own_worn_items", before.worn_item_ids, after.worn_item_ids)
    changes.update(physical_observations.difference(before, after))
    changes.update(scene_difference(before, after))
    if not changes:
        return None
    return _bounded(
        {
            "observation": "host_state_difference",
            "scene_id": after.scene_id,
            "cause": "unknown",
            **changes,
        }
    )


def _sets(changes: dict, prefix: str, before: tuple[str, ...], after: tuple[str, ...]) -> None:
    for suffix, values in (
        ("added", set(after) - set(before)),
        ("removed", set(before) - set(after)),
    ):
        if values:
            changes[f"{prefix}_{suffix}"] = sorted(values)


def _bounded(data: dict) -> str:
    # Preserve valid JSON and declare each omitted list tail. The full typed
    # frame remains in Source.facts for comparison, restore and source hashing.
    omitted: dict[str, int] = {}
    while True:
        encoded = json.dumps({**data, "omitted": omitted}, ensure_ascii=False, sort_keys=True)
        if len(encoded) <= 2000:
            return encoded
        background = (
            next(
                (
                    key
                    for key in ("owned_items", "worn_item_ids", "placed_items", "visible_actor_ids")
                    if isinstance(data.get(key), list) and data[key]
                ),
                None,
            )
            if data.get("last_observed_scene")
            else None
        )
        key = background or max(
            (key for key, value in data.items() if isinstance(value, list) and value),
            key=lambda key: len(json.dumps(data[key])),
            default=None,
        )
        if key is None:
            raise ValueError("CHPM world observation exceeds its text budget.")
        data[key].pop()
        omitted[key] = omitted.get(key, 0) + 1
