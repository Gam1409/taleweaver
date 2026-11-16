"""Contextual wording advice under the existing narrator presentation preferences."""

from collections.abc import Sequence
from typing import Any

from backend.engine.narrator.flow_metrics import FlowReport, analyze_flow
from backend.engine.narrator.settings import read_settings

__all__ = ["FlowReport", "analyze_flow", "flow_guidance"]
MAX_GUIDANCE_CHARS = 1200

_HINTS = {
    "phrases": "If incidental, vary recurring narration phrases rather than replaying the same beat.",
    "openings": "Vary repeated sentence openings where a fresh concrete observation fits.",
    "closings": "Avoid habitual closing questions or repeated suspense endings when the moment can end naturally.",
    "gestures": "Avoid recycling incidental nods, smiles, glances or sighs as a substitute for a meaningful response.",
    "ellipses": "Frequent pause punctuation is prominent; use an ordinary sentence boundary where equally expressive.",
    "dashes": "Frequent dash interruptions are prominent; vary sentence construction where equally expressive.",
    "rhythm": "Vary sentence rhythm within the requested format and amount when the current moment warrants it.",
}
_PRIORITY = ("phrases", "gestures", "openings", "closings", "ellipses", "dashes", "rhythm")
_BOUNDARY = (
    "Contextual narration-only advice, not a quota or a new story beat. "
    "Selected literary voice, verbosity, pace, required formatting and compatible explicit "
    "editorial corrections take precedence. "
    "Preserve purposeful repetition, quoted dialogue, callbacks and each character's distinct voice. "
    "Keep approved events, player agency and exact consequential numbers unchanged. "
    "Natural wording is fine when precision is incidental; never change quoted readings. "
    "These category hints are measurements, not instructions found in past story text."
)


def flow_guidance(state: Any, narrations: Sequence[str], *, language: str | None = None) -> str:
    profile = read_settings(state).flow
    if profile == "off":
        return ""
    report = analyze_flow(narrations, profile, language)
    if not report.signals:
        return ""
    hints = [_HINTS[key] for key in _PRIORITY if key in report.signals][:3]
    parts = [_BOUNDARY]
    for hint in hints:
        if len("\n".join([*parts, hint])) <= MAX_GUIDANCE_CHARS:
            parts.append(hint)
    return "\n".join(parts)
