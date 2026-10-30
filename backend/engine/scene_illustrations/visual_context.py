"""Own the frozen visual context independently of providers and LLM calls."""

from copy import deepcopy
from dataclasses import dataclass

from backend.engine.visual_text import visual_text


@dataclass(frozen=True)
class VisualContext:
    passage: str
    facts: dict
    tone: str

    @classmethod
    def from_snapshot(cls, snapshot: dict, tone: str = "") -> "VisualContext":
        return cls(visual_text(snapshot["narration"]), deepcopy(snapshot["visible_facts"]), tone)
