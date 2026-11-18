"""Reject exact current owner contradictions before a buffered reply is published.

This is a turn-local audit of typed, source-bound observations, not another state
owner or a prose classifier. Unknown facts and intermediate events stay with their
existing reconciliation policies.
"""

from collections import Counter
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any

from backend.core.state_rejection_trace import reject
from backend.engine import turn_controls
from backend.engine.chpm.control_settings import read as read_control_settings
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.state import KEY
from backend.engine.clothing.context import actor_records
from backend.engine.clothing.profiles import load_profile
from backend.engine.clothing.projection import item_wear_state
from backend.engine.clothing.visuals import session_objects
from backend.engine.narrated_items.schema import ItemAction
from backend.engine.npc_actions.control import validated_outcomes
from backend.engine.scene_staging.schema import SceneDelta, SceneExtraction
from backend.engine.turn_replay import drafts
from backend.engine.visual_novel.continuity import possession_snapshot

OBSERVATIONS = frozenset({"observed_possession", "observed_wear", "observed_placement"})


@dataclass
class Check:
    control: dict
    scene_id: str
    narration: str
    publications: dict[str, str]
    items: list[ItemAction] = field(default_factory=list)
    poses: list[SceneDelta] = field(default_factory=list)


def _published(manager: Any) -> dict[str, str]:
    turn = getattr(manager, "_chpm_turn", None)
    if (
        turn is None
        or turn.initial.settings.mode != "live"
        or not turn.initial.settings.action_tools
        or read_control_settings((manager.state.entity_states or {}).get(KEY))
        != turn.initial.settings
        or not turn_controls.bind_current(manager, turn.control)
    ):
        return {}
    binding = turn_controls.binding(turn.control)
    outcomes = validated_outcomes(turn)
    return {
        actor: turn_controls.fingerprint(rows)
        for actor, rows in outcomes.items()
        if _published_actor(manager, turn, actor, rows, binding)
    }


def _published_actor(
    manager: Any, turn: Any, actor: str, rows: list, binding: turn_controls.Binding
) -> bool:
    draft = getattr(turn, "action_drafts", {}).get(actor)
    if draft is None or not draft.approved or draft.published_results != rows:
        return False
    scope = draft.scope
    return (
        scope.session_id,
        scope.actor_id,
        scope.scene_id,
        scope.input_id,
        scope.input_revision,
        scope.input_hash,
    ) == (
        manager.game_id,
        actor,
        manager.state.current_scene_id,
        binding.input_id,
        binding.input_revision,
        binding.input_hash,
    ) and turn_controls.bind_current(manager, scope.control, observation=scope.observation)


def begin(manager: Any, narration: str) -> None:
    """A new extraction replaces any prior attempt's transient observations."""
    manager._npc_narration_fence = None
    publications = _published(manager)
    if publications:
        manager._npc_narration_fence = Check(
            deepcopy(manager._chpm_turn.control),
            manager.state.current_scene_id,
            narration,
            publications,
        )


def _current(manager: Any) -> Check | None:
    check = getattr(manager, "_npc_narration_fence", None)
    if (
        isinstance(check, Check)
        and check.scene_id == manager.state.current_scene_id
        and turn_controls.bind_current(manager, check.control)
    ):
        return check
    return None


def _grounded(check: Check, proposal: Any) -> bool:
    span = proposal.evidence_span
    return span is not None and span.matches(check.narration, proposal.evidence)


def items(manager: Any, actions: Sequence[ItemAction]) -> None:
    check = _current(manager)
    if check is None:
        return
    check.items.extend(
        action.model_copy(deep=True)
        for action in actions
        if action.basis in OBSERVATIONS
        and action.item_id is not None
        and action.destination_owner in check.publications
        and (
            action.basis == "observed_placement" or action.source_owner == action.destination_owner
        )
        and _grounded(check, action)
    )


def poses(manager: Any, extraction: SceneExtraction, *, external: dict) -> None:
    check = _current(manager)
    if check is None:
        return
    counts = Counter(change.entity_id for change in extraction.changes)
    check.poses.extend(
        change.model_copy(deep=True)
        for change in extraction.changes
        if change.entity_id in check.publications
        and change.performer_id == change.entity_id
        and change.cause is None
        and change.entity_id not in external
        and not change.clear
        and counts[change.entity_id] == 1
        and _grounded(check, change)
    )


def _item_conflict(action: ItemAction, actors: dict, snapshot: Any) -> dict:
    actor = actors.get(action.destination_owner)
    owner = snapshot.owners.get(action.item_id)
    if actor is None or owner is None:
        return {}
    identity = {"actor_id": action.destination_owner, "item_id": action.item_id}
    if owner != action.destination_owner:
        return {**identity, "field": "owner", "actual": owner, "proposed": action.destination_owner}
    if action.basis == "observed_possession":
        return {}  # Possession alone never asserts that a garment was removed.
    conflict = _wear_conflict(action, actor)
    return {**identity, **conflict} if conflict else {}


def _wear_conflict(action: ItemAction, actor: dict) -> dict:
    if action.item_id is None:
        return {}
    wear = item_wear_state(
        actor["visual_profile"],
        actor["resolved_inventory"],
        action.item_id,
        equipment=actor["equipment"],
    )
    if wear == "carried":
        return {"field": "worn", "actual": False, "proposed": True}
    profile = load_profile(actor["visual_profile"])
    current = (
        next((row for row in profile.worn if row.item_id == action.item_id), None)
        if profile
        else None
    )
    if current is None:
        return {}
    if action.attachment_slot is not None and action.attachment_slot != current.attachment_slot:
        return {
            "field": "attachment_slot",
            "actual": current.attachment_slot,
            "proposed": action.attachment_slot,
        }
    if action.uncovered_regions is not None and set(action.uncovered_regions) != set(
        current.uncovered_regions
    ):
        return {
            "field": "uncovered_regions",
            "actual": current.uncovered_regions,
            "proposed": action.uncovered_regions,
        }
    return {}


def _pose_conflicts(manager: Any, poses: list[SceneDelta], actors: dict, rows: list) -> list[dict]:
    from backend.engine.scene_staging.shared import _cast
    from backend.engine.scene_staging.state import project

    cast = _cast(manager, actors, rows)
    known = {person["id"] for person in cast}
    current = project(manager.state, cast)
    issues: list[dict] = []
    for change in poses:
        actual = current.get(change.entity_id, {})
        proposed = {
            "posture": change.posture if change.posture != "unknown" else None,
            "placement": change.placement.model_dump()
            if change.placement
            and change.placement.target_kind == "character"
            and change.placement.target in known - {change.entity_id}
            and change.placement.relation != "unknown"
            else None,
        }
        issues.extend(
            {"actor_id": change.entity_id, "field": name, "actual": actual[name], "proposed": value}
            for name, value in proposed.items()
            if value is not None and name in actual and actual[name] != value
        )
    return issues


async def enforce(manager: Any, narration: str) -> None:
    """Use final owner state, never an arbitrary rejection diagnostic or old echo."""
    check = _current(manager)
    manager._npc_narration_fence = None
    if check is None or narration != check.narration:
        return
    published = _published(manager)
    actors = {actor for actor, proof in check.publications.items() if published.get(actor) == proof}
    if not actors or not (check.items or check.poses):
        return
    rows = await session_objects(manager.db, manager.game_id)
    if not turn_controls.bind_current(manager, check.control):
        return
    records = actor_records(manager, rows)
    snapshot = possession_snapshot(manager, rows)
    issues = [
        issue
        for action in check.items
        if action.destination_owner in actors
        and (issue := _item_conflict(action, records, snapshot))
    ]
    issues.extend(
        _pose_conflicts(
            manager, [row for row in check.poses if row.entity_id in actors], records, rows
        )
    )
    if not issues:
        return
    reject(
        "npc_actions",
        "narration_owner_contradiction",
        "Current narration contradicts an authoritative command-owned state.",
        control=check.control,
        publication_hashes=check.publications,
        narration_hash=sha256(narration.encode()).hexdigest(),
        contradictions=issues,
    )
    # This candidate was buffered, so recovery must not expose it as visible prose.
    drafts.observe(manager, "")
    raise ChpmError(
        "Current narration contradicts authoritative owner state; no reply was published."
    )
