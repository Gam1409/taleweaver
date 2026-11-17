"""Bind local pose requests to the staging owner and the current observer frame."""

from typing import TYPE_CHECKING, Any

from backend.engine.npc_actions.contracts import Approach, Pose
from backend.engine.scene_staging.commands import CommandProof, apply_command
from backend.engine.scene_staging.schema import Placement, Posture
from backend.engine.scene_staging.state import KEY

if TYPE_CHECKING:
    from backend.engine.npc_actions.preview import Scope


def apply(scope: "Scope", states: dict, request: Pose | Approach, index: int) -> tuple[dict, dict]:
    from backend.engine.npc_actions.preview import operation_identity

    identity, digest = operation_identity(scope, request, index)
    proof = CommandProof(
        command_id=identity,
        actor_id=scope.actor_id,
        scene_id=scope.scene_id,
        input_id=scope.input_id,
        input_revision=scope.input_revision,
        request_hash=digest,
        operation=request.tool,
    )
    placement = None
    posture: Posture = (
        request.posture
        if isinstance(request, Pose)
        else "on_all_fours"
        if request.mode == "crawl"
        else "standing"
    )
    if isinstance(request, Approach):
        target = scope.player_id if request.target_id == "@player" else request.target_id
        actors = {person["id"] for person in scope.cast}
        placement = Placement(
            relation="near",
            target_kind="character" if target in actors else "scene_object",
            target=target,
        )
    changed = apply_command(
        states,
        scene_id=scope.scene_id,
        cast=list(scope.cast),
        actor_id=scope.actor_id,
        proof=proof,
        enabled=scope.staging_enabled,
        posture=posture,
        placement=placement,
        scene_objects=scope.scene_objects,
    )
    effect: dict[str, Any] = {
        "posture": posture,
        **(
            {"placement": placement.model_dump(), "mode": request.mode}
            if placement and isinstance(request, Approach)
            else {}
        ),
    }
    previous = states.get(KEY, {}).get("actors", {}).get(scope.actor_id, {})
    current = changed[KEY]["actors"][scope.actor_id]
    if isinstance(request, Pose) and "placement" in previous and "placement" not in current:
        effect["placement"] = None
    return changed, effect
