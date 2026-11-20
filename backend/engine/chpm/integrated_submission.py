"""Accept an isolated cognitive submission, then execute its optional selected action."""

from collections.abc import Sequence
from copy import deepcopy
from typing import Any

from backend.engine.chpm import (
    cognitive_proposal,
    inference,
    json_contract,
    parallel_budget,
    proposal_attempt,
    wire_normalization,
)
from backend.engine.chpm.agent_tools import Tools
from backend.engine.chpm.errors import StaleControlError
from backend.engine.chpm.host_state import Mind
from backend.engine.chpm.proposal_references import ReferenceDraft
from backend.engine.chpm.schema import Decision, Settings, Usage
from backend.engine.chpm.two_phase_decision import PhysicalDevelopmentDraft, PhysicalDraft
from backend.engine.npc_actions.selected_sources import Choice


async def submit(
    manager: Any,
    settings: Settings,
    usage: Usage,
    prepared: cognitive_proposal.Prepared,
    raw: str | None,
    *,
    tools: Tools,
    llm: Any,
    captured: dict,
    seen_ids: set[str],
) -> tuple[Decision, Mind]:
    physical = settings.npc_decision_mode == "two_phase"
    parallel_budget.dispatched("physical_intent_accepted" if physical else "proposal")

    def accept(value: ReferenceDraft) -> tuple[Decision, Mind, Sequence[Choice] | None]:
        # Capture only the candidate which passes the entire existing acceptance pipeline,
        # including any in-budget repair. A rejected raw response has no command authority.
        decision, mind = prepared.accept(value)
        if isinstance(value, (PhysicalDraft, PhysicalDevelopmentDraft)):
            return decision, mind, value.physical_intent.steps
        if physical:
            raise StaleControlError("The two-phase actor received a legacy decision contract.")
        return decision, mind, None

    async def initial() -> ReferenceDraft:
        candidate = None
        try:
            if raw is None:
                raise ValueError("Use submit_decision with the complete grounded proposal.")
            candidate = json_contract.decode(raw)
            # This response belongs to this exact dispatch. Only the host's envelope
            # field can be restored; an explicit stale scope and all evidence IDs
            # still go through the ordinary identifier and current-attempt checks.
            if (
                "reference_scope" in prepared.schema.model_fields
                and "reference_scope" not in candidate
            ):
                candidate["reference_scope"] = prepared.references.scope
            candidate, corrections = wire_normalization.normalize(
                prepared.schema, candidate, prepared.identifiers
            )
            usage.format_repairs += len(corrections)
            parsed = prepared.schema.model_validate(deepcopy(candidate))
            json_contract.validate_identifiers(prepared.schema, candidate, prepared.identifiers)
            return parsed
        except ValueError as exc:
            raise inference.InvalidResponseError(
                "CHPM integrated proposal invalid: " + inference.validation_feedback(exc),
                candidate=candidate,
            ) from exc

    decision, mind, steps = await proposal_attempt.request(
        manager,
        settings,
        usage,
        prepared.instruction,
        prepared.payload,
        prepared.schema,
        prepared.identifiers,
        accept,
        initial=initial,
        reserved_execution=int(physical),
        diagnose=prepared.diagnose,
    )
    if steps is None:
        return decision, mind
    from backend.engine.chpm import two_phase_selection

    report = await two_phase_selection.execute(
        manager, settings, usage, tools, llm, captured, seen_ids, steps
    )
    return Decision.model_validate(
        {**decision.model_dump(), "agent_audit": [*decision.agent_audit, *report]}
    ), mind
