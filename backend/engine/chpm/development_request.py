"""Rare consolidation shares the proposal call; oversized optional work is visibly deferred."""

from typing import Literal, NamedTuple

from backend.engine.chpm import (
    appraisal_context,
    cognitive_context,
    compact_decision,
    development,
    development_context,
    motivation,
    proposal_actions,
    proposal_references,
    two_phase_decision,
)
from backend.engine.chpm.appraisal_contracts import GroundedProposal
from backend.engine.chpm.core.contracts import Belief
from backend.engine.chpm.development_contracts import DevelopmentProposal
from backend.engine.chpm.host_state import Mind, Source
from backend.engine.chpm.schema import AgendaEntry, Observation, Settings


class Prepared(NamedTuple):
    window: appraisal_context.Window
    motives: motivation.Catalogue
    payload: dict
    identifiers: dict
    schema: type[GroundedProposal]
    instruction: str
    sources: dict[str, development_context.Episode]
    status: Literal["available", "not_yet_eligible", "deferred_input_budget"]


def wire_schema(
    settings: Settings, development: bool, actions: bool
) -> type[proposal_references.ReferenceDraft]:
    base = (
        two_phase_decision.wire_schema(development)
        if settings.npc_decision_mode == "two_phase"
        else proposal_actions.wire_schema(development, actions)
    )
    return compact_decision.schema_for(base) if settings.decision_detail == "compact" else base


def prepare(
    mind: Mind,
    observation: Observation,
    supplied: dict,
    entries: list[AgendaEntry],
    settings: Settings,
    instruction: str,
    *,
    pinned: dict[str, tuple[str, Source, str]] | None = None,
    pinned_beliefs: dict[str, Belief] | None = None,
    focus_subjects: tuple[str, ...] = (),
    reference_binding: dict | None = None,
) -> Prepared:
    if settings.decision_detail == "compact":
        # Keep cached full decisions distinct even when the visible evidence is identical.
        supplied = {**supplied, "decision_detail": "compact"}
    available = development_context.episodes(
        mind, query=observation.player_request, focus_subjects=focus_subjects
    )
    allowed = development_context.eligible(mind, available)
    body = development_context.payload(mind, available if allowed else {})
    body["status"] = "available" if allowed else "not_yet_eligible"
    if allowed:
        try:
            packed = cognitive_context.pack(
                mind,
                observation,
                supplied,
                entries,
                settings,
                proposal_references.instructions(instruction + development.INSTRUCTIONS),
                schema=DevelopmentProposal,
                wire_schema=wire_schema(settings, True, False),
                pinned=pinned,
                pinned_beliefs=pinned_beliefs,
                focus_subjects=focus_subjects,
                extra={"development_context": body},
                reference_episodes=available,
                reference_binding=reference_binding,
            )
            return Prepared(
                *packed,
                DevelopmentProposal,
                proposal_references.instructions(instruction + development.INSTRUCTIONS),
                available,
                "available",
            )
        except cognitive_context.ContextBudgetError:
            body["status"] = "deferred_input_budget"
            body["basis"] = []
    # This response schema cannot propose development. Keep its status and
    # existing tendencies, but omit rules for that unavailable operation.
    body = {key: body[key] for key in ("policy", "current_tendencies", "basis", "status")}
    packed = cognitive_context.pack(
        mind,
        observation,
        supplied,
        entries,
        settings,
        proposal_references.instructions(instruction),
        extra={"development_context": body},
        wire_schema=wire_schema(settings, False, False),
        pinned=pinned,
        pinned_beliefs=pinned_beliefs,
        focus_subjects=focus_subjects,
        reference_binding=reference_binding,
    )
    return Prepared(
        *packed,
        GroundedProposal,
        proposal_references.instructions(instruction),
        {},
        "deferred_input_budget" if allowed else "not_yet_eligible",
    )
