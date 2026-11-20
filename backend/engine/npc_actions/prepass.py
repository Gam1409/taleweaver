"""Keep VN portable placements source-bound before the command owner runs."""

from collections import defaultdict
from typing import Any

from backend.core.state_rejection_trace import reject
from backend.engine.chpm.control_settings import read
from backend.engine.chpm.state import KEY
from backend.engine.gameplay.movement_intent import PlayerTraversal
from backend.engine.mutation_targets import TargetIndex
from backend.engine.visual_novel.continuity import possession_snapshot
from backend.engine.visual_novel.movement_sources import resolve

INSTRUCTIONS = """
NPC COMMAND PLACEMENT: When npc_command_control is supplied, portable OBJECT
updated_entities.spatial_position and moved_entities placements require the existing
movement_source: current_player_action + resolved_external_effect, with an exact
supplied player:pN passage. Use it only for a resolved physical effect of the
player's own current action, such as placing or carrying the object. A request for
an NPC to take/give/move something, an intention, or a reference to earlier prose
does not establish that effect. Leave those placement fields empty for the NPC's
command API and completed-narration owners. Do not preapply their expected result
through an object's position. A portable object can travel to another room here
only with the player's already-confirmed current traversal to that same room.
PLAYER ITEM OPERATIONS: Every player_item_actions proposal explicitly identifies
performer_id from player_item_executor_id or a supplied present character ID;
use null if unresolved. The performer is distinct from a recipient or clothing
target. A player speaking to an NPC does not make the player the performer.
Only the host-bound player's performed operations may execute here. NPC proposals
remain deferred, including an expected agreement. Cite an exact supplied player:pN
passage and use basis=performed only for an actual completed action.
take moves an accessible existing item to the player, including resolved theft;
give/drop/consume require the player to carry it at that step. give needs the
exact present recipient/container target_id. destroy removes an available object.
These custody operations otherwise omit target_id. Player-performed wardrobe
assistance uses wear/remove/adjust with an existing item_id and target_id plus
the corresponding wardrobe_actions entry. acquire_garment uses target_id and
creation_ref (the matching garment_creations index), omitting item_id; its logical
source and clothing policies are still checked by the clothing owner. Never use
these player operations for an NPC's own choice. At most six operations per plan.
Raw inventory/new_inventory/spawn/deletion fields
cannot independently change custody while this control is enabled. For a request
to an NPC, leave player_item_actions empty and let its action owner decide.
An NPC choice, even an expected agreement, is not the player's performed action.
Fresh voluntary wardrobe choices for controlled actors likewise await that owner;
completed player assistance and established-wear recovery keep their normal checks.
Gifts from a controlled giver defer that NPC's voluntary giving. Only a linked
performed player acquire_garment may proceed as the player's own external action.
Keep independent object updates separate from an unconfirmed placement. A missing
or rejected placement is deferred, not a fictional failed attempt or obstacle.
"""


def enabled(state: Any) -> bool:
    settings = read((getattr(state, "entity_states", None) or {}).get(KEY))
    return (
        settings.mode == "live"
        and settings.workflow == "integrated"
        and settings.action_tools
        and settings.control_scope == "dialogue"
    )


def instructions(state: Any) -> str:
    return INSTRUCTIONS if enabled(state) else ""


def context(state: Any) -> dict:
    if not enabled(state):
        return {}
    settings = read((state.entity_states or {}).get(KEY))
    return {
        "controlled_actor_ids": sorted(settings.actor_ids),
        "portable_object_placement_source": "current_player_action + resolved_external_effect",
        "unproven_placements": "defer to command or completed-narration owners",
        "player_item_executor_id": "__player__",
        "item_operations": "proposed player actions; canonical owners validate and apply",
    }


def defer_wardrobe(
    state: Any, change: Any, *, item_plan: Any = None, creation_ref: int | None = None
) -> bool:
    """The preliminary model cannot approve a fresh controlled actor's own wardrobe choice."""
    if not enabled(state):
        return False
    if change.source != "player_action":
        return False
    from backend.engine.visual_novel.player_items import acquired, assisted

    controlled = set(context(state)["controlled_actor_ids"])
    recipient = change.actor_id in controlled
    giver = getattr(change, "acquisition", None) == "gift" and change.source_id in controlled

    # A generated approval is not the live actor's decision. Player assistance
    # keeps the clothing owner's consent checks and needs its own validated operation.
    return (
        recipient
        and not assisted(item_plan, change, creation_ref=creation_ref)
        or giver
        and not acquired(item_plan, change, creation_ref=creation_ref)
    )


def _portable(rows: list[Any], state: Any) -> list[dict]:
    result = []
    states = state.entity_states or {}
    for row in rows:
        override = states.get(row.id, {})
        override = override if isinstance(override, dict) else {}
        if row.entity_type == "OBJECT" and override.get(
            "is_portable", getattr(row, "is_portable", True)
        ):
            result.append({"id": row.id, "name": row.name})
    return result


def _placements(proposal: Any, index: TargetIndex) -> dict[str, list[tuple[str, Any]]]:
    result: dict[str, list[tuple[str, Any]]] = defaultdict(list)
    for row in getattr(proposal, "updated_entities", None) or []:
        identifier = index.resolve(row.entity_id)
        if identifier and row.spatial_position is not None:
            result[identifier].append(("spatial_position", row))
    for row in getattr(proposal, "moved_entities", None) or []:
        identifier = index.resolve(row.entity_id)
        if identifier and (row.to_spatial_position is not None or row.to_scene_id is not None):
            result[identifier].append(("to_spatial_position", row))
    return result


def _travel(manager: Any, event: Any, row: Any, source: Any, destinations: set[str]) -> None:
    if row.to_scene_id in {None, source.scene_id}:
        return
    travel = getattr(manager, "_confirmed_player_travel", None)
    if not isinstance(travel, PlayerTraversal) or (
        travel.message_id != source.message_id
        or travel.source != source.text
        or travel.origin != source.scene_id
        or travel.destination != row.to_scene_id
        or event.new_scene_id != travel.destination
        or row.to_scene_id not in destinations
    ):
        raise ValueError("Portable object travel requires the player's confirmed traversal.")


async def _check(
    manager: Any, event: Any, current: list, original: list, destinations: set[str]
) -> None:
    if len(current) != 1 or len(original) != 1:
        raise ValueError("Portable placement requires one unambiguous original proposal.")
    field, row = current[0]
    original_field, proposal = original[0]
    if field != original_field or getattr(row, field) != getattr(proposal, field):
        raise ValueError("Portable placement changed after its source-bound proposal.")
    if field == "to_spatial_position" and row.to_scene_id != proposal.to_scene_id:
        raise ValueError("Portable object destination changed after its proposal.")
    proof = getattr(proposal, "movement_source", None)
    if proof is None or (proof.kind, proof.basis) != (
        "current_player_action",
        "resolved_external_effect",
    ):
        raise ValueError("Portable placement needs a resolved current-player physical source.")
    source, _ = await resolve(manager, proof)
    if (
        source.message_id != getattr(manager, "_vn_player_message_id", None)
        or source.role != "user"
        or source.scene_id != manager.state.current_scene_id
    ):
        raise ValueError("Portable placement belongs to a different input or scene.")
    if field == "to_spatial_position":
        _travel(manager, event, row, source, destinations)


def _defer(event: Any, identifier: str, index: TargetIndex) -> None:
    for row in event.updated_entities or []:
        if index.resolve(row.entity_id) == identifier:
            row.spatial_position = None
    event.moved_entities = [
        row for row in event.moved_entities or [] if index.resolve(row.entity_id) != identifier
    ]


async def resolve_placements(
    manager: Any, event: Any, rows: list[Any], movement: dict
) -> list[str]:
    """Filter only direct portable placements; inventory and independent fields keep their owners."""
    if not enabled(manager.state):
        return []
    index = TargetIndex(_portable(rows, manager.state))
    current = _placements(event, index)
    original = _placements(getattr(manager, "_vn_movement_proposal", None), index)
    available = possession_snapshot(manager, rows).items
    destinations = set(
        movement.get("actors", {}).get("__player__", {}).get("allowed_destinations", [])
    )
    rejected = []
    for identifier, placements in current.items():
        try:
            if identifier not in available:
                raise ValueError("Portable placement target is no longer available in this scene.")
            await _check(manager, event, placements, original.get(identifier, []), destinations)
        except ValueError as exc:
            reject(
                "movement",
                "npc_actions.prepass_placement_deferred",
                str(exc),
                target_id=identifier,
                proposal=original.get(identifier, []),
            )
            _defer(event, identifier, index)
            rejected.append(identifier)
    return rejected
