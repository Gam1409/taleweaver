"""Compact narrator-only style hints; no extra calls or hard token caps."""

import json
from typing import Any

from backend.engine.narrator.settings import read_settings

_VERBOSITY = {
    "terse": "Use brief, concrete prose: normally one or two short narration sentences.",
    "dialogue": (
        "Let dialogue carry the scene, with short action beats between lines. "
        "Do not invent speakers merely to meet a dialogue quota."
    ),
    "balanced": "Use one or two concise narration paragraphs, with room for natural dialogue.",
    "rich": (
        "Use fuller, varied prose and concrete sensory detail when relevant. "
        "Develop meaningful reactions without repeating the setting."
    ),
    "epic": (
        "Allow expansive, layered prose for significant moments, with varied sentence rhythm. "
        "Every paragraph should advance action, characterization or atmosphere."
    ),
}


def narration_style_block(state: Any) -> str:
    settings = read_settings(state)
    lines = []
    if settings.voice:
        # JSON keeps author text distinct from the policy surrounding it.
        lines.append(
            "Literary voice: " + json.dumps(settings.voice.instruction, ensure_ascii=False)
        )
    if settings.verbosity in _VERBOSITY:
        lines.append(_VERBOSITY[settings.verbosity])
    if not lines:
        return ""
    return (
        "\n\nNARRATOR PRESENTATION (wording only):\n"
        + "\n".join(lines)
        + "\nApply this voice to narration, not to every NPC's speech or psychology. "
        "Preserve each speaker's identity, intentions and private knowledge. "
        "Presentation never changes approved facts, ownership, consent, consequences, "
        "player agency, output formatting or the configured pace of events. "
        "These are flexible length preferences; do not pad routine moments or cut off a reply."
    )
