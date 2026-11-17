"""Turn-local NPC command previews; inspecting or planning never changes the world."""

from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Literal

from backend.engine.clothing.changes import preview as wardrobe_preview
from backend.engine.clothing.profiles import garment_for_item
from backend.engine.clothing.projection import known_worn_item_ids
from backend.engine.narrated_items.commands import transfer
from backend.engine.npc_actions.contracts import (
    Adjust,
    ChangeState,
    Discard,
    Give,
    Item,
    Move,
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

MAX_ACTIONS = 16


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


@dataclass
class Draft:
    scope: Scope
    start_index: int = 0
    requests: list[Request] = field(default_factory=list)
    receipts: list[dict] = field(default_factory=list)
    approved: bool = False
    published_results: list[dict] | None = field(default=None, init=False)
    _actors: dict = field(init=False, repr=False)
    _possessions: Possessions = field(init=False, repr=False)
    _states: dict = field(init=False, repr=False)
    _departed: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.scope.actor_id not in self.scope.actors:
            raise ValueError("The command actor is unavailable in this scene.")
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
            names.add("wear_item")
        actor = self._actors[self.scope.actor_id]
        worn = known_worn_item_ids(
            actor["visual_profile"], actor["resolved_inventory"], equipment=actor["equipment"]
        )
        if worn:
            names.update({"take_off_item", "adjust_clothing"})
        return names

    def execute(self, request: Request) -> dict:
        if self.approved:
            return {"status": "plan_closed", "message": "This decision has already been submitted."}
        if isinstance(request, Discard):
            self.requests.clear()
            self.receipts.clear()
            self._reset()
            return {"status": "discarded", "count": 0}
        rejection = self._rejection(request)
        if rejection:
            return rejection
        try:
            receipt = self._preview(request)
        except ValueError as exc:
            return {"status": "blocked", "message": str(exc)[:320]}
        self.requests.append(request.model_copy(deep=True))
        self.receipts.append(receipt)
        return {
            "status": "staged",
            "index": len(self.requests) - 1,
            "effect": receipt,
            "world_changed": False,
        }

    def _rejection(self, request: Request) -> dict | None:
        if len(self.requests) >= MAX_ACTIONS:
            return {"status": "action_limit", "message": "Submit or discard the existing plan."}
        if self._departed:
            return {
                "status": "scene_frame_ended",
                "message": "Room travel ends this scene's plan. Submit it or discard it first.",
            }
        if isinstance(request, Item) and request.item_id not in self.scope.accessible_ids:
            return {
                "status": "unavailable_entity",
                "message": "Use an exact currently accessible item ID; find or inspect it first.",
            }
        return None

    def _preview(self, request: Request) -> dict:
        if isinstance(request, Move):
            if request.destination_scene_id not in self.scope.destinations:
                raise ValueError("The destination is not an available permitted route.")
            self._departed = True
            return {"destination_scene_id": request.destination_scene_id}
        if isinstance(request, (Take, Give, PutDown)):
            return self._transfer(request)
        if isinstance(request, (Wear, TakeOff, Adjust)):
            return self._wardrobe(request)
        if isinstance(request, (ChangeState, Use)):
            return self._property(request)
        raise ValueError("This action is unavailable to this controller.")

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
        )
        self._actors, self._possessions = changed, possessions
        return {key: value for key, value in receipt.items() if key != "item"} | {
            "item_id": request.item_id
        }

    def _wardrobe(self, request: Wear | TakeOff | Adjust) -> dict:
        operation: Literal["wear", "remove", "adjust"] = (
            "wear"
            if isinstance(request, Wear)
            else "remove"
            if isinstance(request, TakeOff)
            else "adjust"
        )
        regions = request.uncovered_regions if isinstance(request, Adjust) else []
        actor = wardrobe_preview(
            self._actors[self.scope.actor_id],
            request.item_id,
            operation,
            regions,
            detailed=self.scope.detailed,
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
    digest = sha256(request.model_dump_json().encode()).hexdigest()
    identity = sha256(
        f"{scope.session_id}:{scope.input_id}:{scope.actor_id}:{index}:{digest}".encode()
    ).hexdigest()
    proof = CommandProof(id="command_" + identity, actor_id=scope.actor_id, operation=request.tool)
    return proof, digest
