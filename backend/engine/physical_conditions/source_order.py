"""Keep changes to one condition in their exact current-narration order."""

from backend.core.text_evidence import unique_span
from backend.engine.physical_conditions.schema import Condition, ConditionProposal


def require_order(
    current: Condition | None,
    proposal: ConditionProposal,
    narration: str,
    message_id: str,
    *,
    manual: bool,
) -> None:
    """Reject older or ambiguous source occurrences for this condition only."""
    if manual or current is None or current.latest.message_id != message_id:
        return
    previous = unique_span(narration, current.latest.quote, current.latest.evidence_span)
    incoming = unique_span(narration, proposal.evidence, proposal.evidence_span)
    if previous is None or incoming is None or incoming.start < previous.end:
        subject = "Item state" if current.kind == "item_state" else "Condition"
        raise ValueError(f"{subject} changes require unambiguous narrative order.")
