"""Structural referent checks on the same atomic preview used by world owners."""

from typing import TYPE_CHECKING

from backend.engine.npc_actions.contracts import Request
from backend.engine.npc_actions.selected_sources import Passage

if TYPE_CHECKING:
    from backend.engine.npc_actions.preview import Draft


class TargetResolutionError(ValueError):
    def __init__(self, code: str, field: str):
        self.code, self.field = code, field
        super().__init__(code)


def known_references(draft: "Draft") -> set[str]:
    return set(draft.scope.accessible_ids | draft.scope.destinations)


def _role(draft: "Draft", field: str) -> set[str]:
    scope = draft.scope
    roles = {
        "item_id": scope.accessible_ids & scope.possessions.items.keys(),
        "recipient_id": (scope.accessible_ids & (scope.actors.keys() | {"@player"}))
        - {scope.actor_id},
        "target_id": scope.accessible_ids,
        "destination_scene_id": scope.destinations,
    }
    return set(roles[field])


def _eligible(draft: "Draft", request: Request, field: str) -> set[str]:
    candidates = _role(draft, field)
    if field != "item_id":
        return candidates - {draft.scope.actor_id} if request.tool == "approach" else candidates
    return candidates & draft.selected_item_candidates(request.tool)


def validate(draft: "Draft", request: Request, passage: Passage) -> None:
    if set(passage.target_refs) - known_references(draft):
        raise TargetResolutionError("unavailable_target", "target_refs")
    for field in ("item_id", "recipient_id", "target_id", "destination_scene_id"):
        if hasattr(request, field):
            _validate_operand(draft, request, passage, field)


def _validate_operand(draft: "Draft", request: Request, passage: Passage, field: str) -> None:
    chosen = getattr(request, field)
    role = _role(draft, field)
    if chosen not in role:
        raise TargetResolutionError("unavailable_target", field)
    references = role & set(passage.target_refs)
    if references and chosen not in references:
        raise TargetResolutionError("selected_target_mismatch", field)
    eligible = _eligible(draft, request, field)
    eligible = eligible & references if references else eligible
    if len(eligible) > 1:
        raise TargetResolutionError("ambiguous_target", field)
    # A known explicitly selected but currently infeasible object remains the
    # existing world owner's rejection, rather than a fabricated parse failure.
    if eligible and chosen not in eligible:
        raise TargetResolutionError("selected_target_mismatch", field)
