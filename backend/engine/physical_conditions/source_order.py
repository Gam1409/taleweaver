"""Keep changes to one condition in their exact current-narration order."""

from backend.core.text_evidence import EvidenceSpan, require_span
from backend.engine.physical_conditions.schema import Condition, ConditionProposal


def _occurrence(text: str, quote: str, span: EvidenceSpan | None) -> tuple[int, int] | None:
    if span is not None:
        require_span(text, quote, span)
        return span.start, span.end
    start = text.find(quote)
    if start < 0 or text.find(quote, start + 1) >= 0:
        return None
    return start, start + len(quote)


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
    previous = _occurrence(narration, current.latest.quote, current.latest.evidence_span)
    incoming = _occurrence(narration, proposal.evidence, proposal.evidence_span)
    if previous is None or incoming is None or incoming[0] < previous[1]:
        subject = "Item state" if current.kind == "item_state" else "Condition"
        raise ValueError(f"{subject} changes require unambiguous narrative order.")
