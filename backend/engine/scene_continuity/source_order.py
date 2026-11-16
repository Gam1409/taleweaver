"""Keep successive updates to one scene fact in their selected source order."""

from backend.core.text_evidence import unique_span

from .schema import Evidence, Record


def require_order(current: Record, source: Evidence, text: str) -> None:
    previous = current.latest
    if (
        source.kind != "narration"
        or previous.kind != source.kind
        or previous.source_id != source.source_id
        or previous.content_hash != source.content_hash
    ):
        return
    before = unique_span(text, previous.quote, previous.evidence_span)
    incoming = unique_span(text, source.quote, source.evidence_span)
    if before is None or incoming is None or incoming.start < before.end:
        raise ValueError("Scene fact changes require unambiguous source order.")
