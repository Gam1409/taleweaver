"""Turn-local NPC command previews; inspecting or planning never changes the world."""

from copy import deepcopy
from dataclasses import dataclass, field, replace
from hashlib import sha256
from typing import TYPE_CHECKING, Literal

from backend.engine import turn_controls
from backend.engine.clothing.changes import preview as wardrobe_preview
from backend.engine.clothing.profiles import garment_for_item
from backend.engine.clothing.projection import item_wear_state
from backend.engine.narrated_items.commands import carried_after, transfer
from backend.engine.npc_actions import control
from backend.engine.npc_actions.contracts import (
    MAX_ACTIONS,
    Adjust,
    Approach,
    ChangeState,
    Discard,
    Give,
    Interact,
    Item,
    Move,
    Pose,
    PutDown,
    Request,
    Take,
    TakeOff,
    Use,
    Wear,
)
from backend.engine.physical_conditions.command_source import CommandProof
from backend.engine.physical_conditions.item_commands import apply_command
from backend.engine.visual_novel.continuity import SCENE, Possessions

if TYPE_CHECKING:
    from backend.engine.chpm.schema import Observation


@dataclass(frozen=True)
class Scope:
    session_id: str
    input_id: str
    actor_id: str
    scene_id: str
    actors: dict
    possessions: Possessions
    states: dict
    accessible_ids: frozenset[str]
    destinations: frozenset[str]
    detailed: bool = False
    minute: int = 0
    input_hash: str = ""
    input_revision: str | None = None
    player_id: str = "@player"
    cast: tuple[dict, ...] = ()
    scene_objects: dict[str, str] = field(default_factory=dict)
    staging_enabled: bool = False
    observation: "Observation | None" = None
    control: dict = field(default_factory=dict)
    public_item_ids: frozenset[str] = frozenset()


@dataclass
class Draft:
    scope: Scope
    start_index: int = 0
    prior_receipts: tuple[dict, ...] = field(default=(), kw_only=True, repr=False)
    requests: list[Request] = field(default_factory=list)
    receipts: list[dict] = field(default_factory=list)
    operations: list[turn_controls.Operation] = field(default_factory=list, init=False, repr=False)
    approved: bool = False
    published_results: list[dict] | None = field(default=None, init=False)
    _actors: dict = field(init=False, repr=False)
    _possessions: Possessions = field(init=False, repr=False)
    _states: dict = field(init=False, repr=False)
    _departed: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.scope.actor_id not in self.scope.actors:
            raise ValueError("The command actor is unavailable in this scene.")
        if not self.scope.control:
            self.scope = replace(self.scope, control=control.local_scope(self.scope))
        self._reset()

    def _reset(self) -> None:
        self._actors = deepcopy(self.scope.actors)
        self._possessions = deepcopy(self.scope.possessions)
        self._states = deepcopy(self.scope.states)
        self._departed = False

    def context(self) -> dict:
        return {
            "status": "pending_not_world_facts",
            "count": len(self.requests),
            "commands": [request.model_dump() for request in self.requests],
            # Full bindings remain on the host. The model needs the handles to
            # relate feedback to its plan, not repeated input hashes per command.
            "operation_ids": [operation.operation_id for operation in self.operations],
            "remaining_commands": MAX_ACTIONS - len(self.requests),
        }

    def working_copy(self) -> tuple[dict, Possessions, dict]:
        """Return an isolated accepted preview for owner publication, never model output."""
        return deepcopy(self._actors), deepcopy(self._possessions), deepcopy(self._states)

    def available_tools(self) -> set[str]:
        if self.approved:
            return set()
        names = {"discard_actions"} if self.requests else set()
        if self._departed:
            return names
        if self.scope.destinations:
            names.add("move_to")
        names.add("interact")
        if self.scope.staging_enabled:
            names.update({"set_pose", "approach"})
        reachable = {
            key
            for key, owner in self._possessions.owners.items()
            if key in self.scope.accessible_ids and owner in {SCENE, self.scope.actor_id}
        }
        if any(self._possessions.owners[key] == SCENE for key in reachable):
            names.add("take_item")
        if reachable:
            # Include capabilities available after acquisition in the same batch;
            # each operation still checks actual custody on the working copy.
            names.update({"put_down_item", "give_item", "change_item_state", "use_item"})
        if any(garment_for_item(self._possessions.items[key]) is not None for key in reachable):
            names.update({"wear_item", "take_off_item", "adjust_clothing"})
        actor = self._actors[self.scope.actor_id]
        if any(
            owner == self.scope.actor_id
            and item_wear_state(
                actor["visual_profile"],
                actor["resolved_inventory"],
                key,
                equipment=actor["equipment"],
            )
            == "worn"
            for key, owner in self._possessions.owners.items()
        ):
            names.update({"take_off_item", "adjust_clothing"})
        return names

    def execute(
        self, request: Request, *, operation: turn_controls.Operation | None = None
    ) -> dict:
        identity, _ = operation_identity(self.scope, request, self.start_index + len(self.requests))
        if operation is not None and (
            not control.bound_to(operation, self.scope.control)
            or operation.actor_id != self.scope.actor_id
            or operation.tool != request.tool
            or operation.command_id not in {None, identity}
        ):
            rejected = turn_controls.operation(
                self.scope.control, request.tool, actor_id=self.scope.actor_id, command_id=identity
            )
            return control.result(rejected, "blocked", reason_code="invalid_operation")
        operation = (
            operation.model_copy(update={"command_id": identity})
            if operation is not None
            else turn_controls.operation(
                self.scope.control, request.tool, actor_id=self.scope.actor_id, command_id=identity
            )
        )
        if self.approved:
            return control.result(operation, "plan_closed", reason_code="plan_closed")
        if isinstance(request, Discard):
            self.requests.clear()
            self.receipts.clear()
            self.operations.clear()
            self._reset()
            return control.result(operation, "discarded", count=0)
        rejection = self._rejection(request)
        if rejection:
            return control.result(operation, rejection, reason_code=rejection)
        try:
            receipt = self._preview(request)
        except ValueError as exc:
            return control.owner_failure(operation, exc)
        self.requests.append(request.model_copy(deep=True))
        self.receipts.append(receipt)
        self.operations.append(operation)
        return control.result(
            operation, "staged", index=len(self.requests) - 1, effect=receipt, world_changed=False
        )

    def _rejection(self, request: Request) -> str | None:
        if len(self.requests) >= MAX_ACTIONS:
            return "action_limit"
        if self._departed:
            return "scene_frame_ended"
        if isinstance(request, Item) and request.item_id not in self.scope.accessible_ids:
            return "unavailable_entity"
        if (
            isinstance(request, (Approach, Interact))
            and request.target_id not in self.scope.accessible_ids
        ):
            return "unavailable_entity"
        return None

    def _preview(self, request: Request) -> dict:
        if isinstance(request, Move):
            if request.destination_scene_id not in self.scope.destinations:
                raise ValueError("The destination is not an available permitted route.")
            self._departed = True
            return {"destination_scene_id": request.destination_scene_id}
        if isinstance(request, (Pose, Approach)):
            from backend.engine.npc_actions.pose_actions import apply as pose_preview

            self._states, effect = pose_preview(
                replace(self.scope, scene_objects=self._scene_objects()),
                self._states,
                request,
                self.start_index + len(self.requests),
            )
            return effect
        if isinstance(request, Interact):
            return {
                "target_id": request.target_id,
                "own_action_attempt": request.action,
                "consequences": "unresolved; requires existing world and narration checks",
            }
        if isinstance(request, (Take, Give, PutDown)):
            return self._transfer(request)
        if isinstance(request, (Wear, TakeOff, Adjust)):
            return self._wardrobe(request)
        if isinstance(request, (ChangeState, Use)):
            return self._property(request)
        raise ValueError("This action is unavailable to this controller.")

    def _scene_objects(self) -> dict[str, str]:
        """Keep fixed visible props and apply this plan's current loose-item custody."""
        return {
            **{
                key: name
                for key, name in self.scope.scene_objects.items()
                if key in self.scope.accessible_ids
                and self._possessions.owners.get(key, SCENE) == SCENE
            },
            **{
                key: item["name"][:120]
                for key, item in self._possessions.items.items()
                if key in self.scope.accessible_ids
                and self._possessions.owners.get(key) == SCENE
                and isinstance(item.get("name"), str)
                and item["name"].strip()
            },
        }

    def _transfer(self, request: Take | Give | PutDown) -> dict:
        operation: Literal["take", "give", "put_down"] = (
            "take"
            if isinstance(request, Take)
            else "give"
            if isinstance(request, Give)
            else "put_down"
        )
        changed, possessions, receipt = transfer(
            self._actors,
            self._possessions,
            self.scope.actor_id,
            request.item_id,
            operation,
            detailed=self.scope.detailed,
            recipient_id=request.recipient_id if isinstance(request, Give) else None,
            position=request.position if isinstance(request, PutDown) else None,
            carried_item_ids=carried_after(
                self.scope.actor_id, (*self.prior_receipts, *self.receipts)
            ),
        )
        self._actors, self._possessions = changed, possessions
        return {key: value for key, value in receipt.items() if key != "item"} | {
            "item_id": request.item_id
        }

    def _wardrobe(self, request: Wear | TakeOff | Adjust) -> dict:
        from backend.engine.clothing.body_schema import WearCommandProof

        operation: Literal["wear", "remove", "adjust"] = (
            "wear"
            if isinstance(request, Wear)
            else "remove"
            if isinstance(request, TakeOff)
            else "adjust"
        )
        regions = request.uncovered_regions if isinstance(request, Adjust) else []
        proof = None
        if isinstance(request, (Wear, Adjust)):
            identity, digest = operation_identity(
                self.scope, request, self.start_index + len(self.requests)
            )
            proof = WearCommandProof(
                command_id=identity,
                actor_id=self.scope.actor_id,
                item_id=request.item_id,
                input_id=self.scope.input_id,
                input_hash=self.scope.input_hash,
                input_revision=self.scope.input_revision,
                request_hash=digest,
                operation=request.tool,
            )
        actor = wardrobe_preview(
            self._actors[self.scope.actor_id],
            request.item_id,
            operation,
            regions,
            detailed=self.scope.detailed,
            proof=proof,
        )
        self._actors[self.scope.actor_id] = actor
        return {"item_id": request.item_id, "operation": operation, "uncovered_regions": regions}

    def _property(self, request: ChangeState | Use) -> dict:
        owned = {
            key for key, owner in self._possessions.owners.items() if owner == self.scope.actor_id
        }
        detail = (
            request.detail
            if isinstance(request, ChangeState)
            else request.remaining_detail
            or ("Used completely." if request.extent == "full" else "Used partly.")
        )
        dimension = request.dimension if isinstance(request, ChangeState) else "usage"
        proof, digest = command_proof(self.scope, request, self.start_index + len(self.requests))
        changed, condition_id = apply_command(
            self._states,
            item_id=request.item_id,
            dimension=dimension,
            detail=detail,
            owned_item_ids=owned,
            proof=proof,
            message_id=self.scope.input_id,
            request_hash=digest,
            session_id=self.scope.session_id,
            minute=self.scope.minute,
            visibility=request.visibility if isinstance(request, ChangeState) else "public",
        )
        self._states = changed
        return {
            "item_id": request.item_id,
            "dimension": dimension,
            "detail": detail,
            "condition_id": condition_id,
        }


def command_proof(scope: Scope, request: ChangeState | Use, index: int) -> tuple[CommandProof, str]:
    identity, digest = operation_identity(scope, request, index)
    proof = CommandProof(id=identity, actor_id=scope.actor_id, operation=request.tool)
    return proof, digest


def operation_identity(scope: Scope, request: Request, index: int) -> tuple[str, str]:
    digest = sha256(request.model_dump_json().encode()).hexdigest()
    identity = sha256(
        f"{scope.session_id}:{scope.input_id}:{scope.actor_id}:{index}:{digest}".encode()
    ).hexdigest()
    return "command_" + identity, digest
