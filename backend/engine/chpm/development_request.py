"""Rare consolidation shares the proposal call; oversized optional work is visibly deferred."""

from typing import Literal, NamedTuple

from backend.engine.chpm import (
    appraisal_context,
    cognitive_context,
    development,
    development_context,
    motivation,
)
from backend.engine.chpm.appraisal_contracts import GroundedProposal
from backend.engine.chpm.development_contracts import DevelopmentProposal
from backend.engine.chpm.host_state import Mind
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


def prepare(
    mind: Mind,
    observation: Observation,
    supplied: dict,
    entries: list[AgendaEntry],
    settings: Settings,
    instruction: str,
) -> Prepared:
    available = development_context.episodes(mind)
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
                instruction + development.INSTRUCTIONS,
                schema=DevelopmentProposal,
                extra={"development_context": body},
            )
            return Prepared(
                *packed,
                DevelopmentProposal,
                instruction + development.INSTRUCTIONS,
                available,
                "available",
            )
        except cognitive_context.ContextBudgetError:
            body["status"] = "deferred_input_budget"
            body["basis"] = []
    packed = cognitive_context.pack(
        mind,
        observation,
        supplied,
        entries,
        settings,
        instruction,
        extra={"development_context": body},
    )
    return Prepared(
        *packed,
        GroundedProposal,
        instruction,
        {},
        "deferred_input_budget" if allowed else "not_yet_eligible",
    )
