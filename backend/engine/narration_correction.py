"""Request-scoped editorial feedback; never stored as story or memory."""

import json
from typing import Annotated

from pydantic import StringConstraints

NarrationCorrection = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]


def append_correction(system: str, correction: str | None) -> str:
    """Keep the stable system prefix intact and append one explicit editorial task."""
    if not correction or not correction.strip():
        return system
    return (
        system + "\n\nEDITORIAL CORRECTION — THIS RESPONSE ONLY (MANDATORY):\n"
        "Apply the player's editorial feedback below to this narration. It is outside the "
        "roleplay: never quote, acknowledge, or turn it into dialogue, a memory, or an event. "
        "It takes precedence over stylistic habits in earlier replies. Keep the required "
        "output format, session language, character agency, and engine-confirmed facts and "
        "outcomes. Feedback is not evidence of a new event or permission to change state. "
        "If it conflicts with those constraints, apply only the compatible presentation changes. "
        "Do not copy repetitive examples from the feedback. Return only the narration.\n"
        "EDITORIAL FEEDBACK (JSON string): " + json.dumps(correction.strip(), ensure_ascii=False)
    )


def correction_applied(correction: str | None, narration: str, warning: str | None) -> bool:
    """Acknowledge delivery only for a complete, nonempty model response, not a fallback."""
    return bool(correction and correction.strip() and narration.strip() and not warning)
