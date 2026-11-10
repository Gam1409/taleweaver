"""Request-scoped source occurrences; no cross-turn lookup by similar or repeated text."""

from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

from backend.core.text_evidence import EvidenceSpan
from backend.core.text_passages import spans

SourceKind = Literal["narration", "scene_description"]


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
        chosen = self._entries.get(reference)
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

    def references(self, *, allow_room: bool = False, minimum: int = 4) -> list[str]:
        return [
            key
            for key, value in self._entries.items()
            if len(value.quote) >= minimum and (allow_room or value.kind == "narration")
        ]
