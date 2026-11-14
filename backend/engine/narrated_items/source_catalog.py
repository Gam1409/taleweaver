"""Request-scoped source occurrences; no cross-turn lookup by similar or repeated text."""

from dataclasses import dataclass
from hashlib import sha256
from itertools import pairwise
from typing import Literal

from backend.core.text_evidence import EvidenceSpan
from backend.core.text_passages import spans

SourceKind = Literal["narration", "scene_description"]
MAX_JOINED_EVIDENCE = 600


@dataclass(frozen=True)
class Citation:
    reference: str
    kind: SourceKind
    quote: str
    span: EvidenceSpan


class Catalog:
    def __init__(self, narration: str, room: str = "", *, scope: str):
        self.narration = narration
        self.room = room
        self._entries: dict[str, Citation] = {}
        self.narration_passages = self._add("narration", narration, "narration", scope)
        self.room_passages = self._add("room", room, "scene_description", scope)
        self._ranges = self._adjacent_ranges()
        self._range_anchors = {
            (row.span.start, row.span.end): self._entries[key.split("..", 1)[0]]
            for key, row in self._ranges.items()
        }

    def coverage_anchor(self, chosen: Citation) -> Citation:
        """A joined proof covers its first occurrence only, never unrelated later facts."""
        if chosen.kind != "narration":
            return chosen
        return self._range_anchors.get((chosen.span.start, chosen.span.end), chosen)

    def _adjacent_ranges(self) -> dict[str, Citation]:
        """Offer at most n-1 short source spans; coverage groups keep the original n."""
        result = {}
        for left_key, right_key in pairwise(self.narration_passages):
            left, right = self._entries[left_key], self._entries[right_key]
            if right.span.end - left.span.start > MAX_JOINED_EVIDENCE:
                continue
            reference = left_key + ".." + right_key.rsplit(":", 1)[1]
            result[reference] = Citation(
                reference,
                "narration",
                self.narration[left.span.start : right.span.end],
                EvidenceSpan(start=left.span.start, end=right.span.end),
            )
        return result

    def _add(self, label: str, text: str, kind: SourceKind, scope: str) -> dict[str, str]:
        token = sha256(f"{scope}\0{label}\0{text}".encode()).hexdigest()[:16]
        result = {}
        for key, passage in spans(text).items():
            reference = f"{label}:{token}:{key}"
            self._entries[reference] = Citation(
                reference, kind, passage.text, EvidenceSpan(start=passage.start, end=passage.end)
            )
            result[reference] = passage.text
        return result

    def resolve(self, reference: str, *, allow_room: bool) -> Citation:
        chosen = self._entries.get(reference) or self._ranges.get(reference)
        if chosen is None:
            raise ValueError("Unknown or stale evidence reference.")
        if chosen.kind == "scene_description" and not allow_room:
            raise ValueError(
                "This state requires current narration, not an authored room description."
            )
        return chosen

    def literal(self, quote: str, *, allow_room: bool) -> Citation:
        choices: list[tuple[SourceKind, str]] = [("narration", self.narration)]
        if allow_room:
            choices.append(("scene_description", self.room))
        found = [(kind, text) for kind, text in choices if quote and quote in text]
        if len(found) != 1:
            raise ValueError("Ambiguous or missing literal evidence; use a source reference.")
        kind, text = found[0]
        start = text.index(quote)
        if text.find(quote, start + 1) >= 0:
            raise ValueError("Ambiguous literal evidence; use a source reference.")
        return Citation("", kind, quote, EvidenceSpan(start=start, end=start + len(quote)))

    def references(
        self, *, allow_room: bool = False, minimum: int = 4, include_ranges: bool = False
    ) -> list[str]:
        available = {**self._entries, **self._ranges} if include_ranges else self._entries
        return [
            key
            for key, value in available.items()
            if len(value.quote) >= minimum and (allow_room or value.kind == "narration")
        ]
