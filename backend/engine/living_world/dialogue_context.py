"""Bounded dialogue evidence and narrator guidance for NPC initiative."""

NARRATION_INITIATIVE = """
NPC INITIATIVE: Let NPCs pursue established motivations and carry their own actions
forward to the next meaningful player choice. Do not ask out of character whether
to continue writing or describing the scene. In-character questions, offers and
necessary clarifications are welcome. Never decide the player's reply, consent,
thoughts or actions. A request to continue narration is not consent to an NPC's
proposal. Respect refusals, established boundaries and authoritative mechanics.
Use scene state silently for continuity; do not recite positions or clothing each turn.
"""


def recent_context(history: list[dict[str, str]] | None) -> list[dict[str, str]]:
    """Keep recent public dialogue as context, never as proof of NPC knowledge."""
    selected: list[dict[str, str]] = []
    remaining = 4800
    for entry in reversed(history or []):
        role = entry.get("role", "")
        content = entry.get("content", "")
        if role not in {"user", "assistant"} or not content.strip():
            continue
        if remaining <= 0 or len(selected) >= 8:
            break
        text = content[: min(1600, remaining)]
        selected.append({"role": role, "content": text})
        remaining -= len(text)
    return list(reversed(selected))
