"""Shared meanings for the existing speech-bound agenda codes, not world actions."""

ACTION_MEANINGS = {
    "goal": "Declared ongoing goal: announce a new lasting personal aim.",
    "commitment": "Spoken ongoing commitment: undertake future or continuing business.",
    "withdraw": "Spoken withdrawal: cancel an ACTIVE owned entry.",
    "report_done": "Spoken completion claim: claim an ACTIVE owned entry done; not world completion.",
}
ACTION_DESCRIPTION = " ".join(f"{code}: {meaning}" for code, meaning in ACTION_MEANINGS.items())
CHANGE_DESCRIPTION = (
    "Spoken agenda change; null for immediate actions/sequences, silent/private resolve, "
    "unchanged agendas or passing reactions. Non-null needs this NPC's own speech now."
)
GLOSSARY = (
    "\nDECLARED AGENDA CODES (agenda_change; not action completion or private intention):\n"
    + "\n".join(f"{code}: {meaning}" for code, meaning in ACTION_MEANINGS.items())
    + "\nnull: no declared change. Immediate actions/ordered steps, silent/private resolve, "
    "unchanged agendas and passing reactions need no new entry.\n"
    "withdraw/report_done copy the ACTIVE owned ID/text exactly. Every non-null change needs "
    "this NPC's own spoken words in this reply; no stock 'I promise' phrase required. "
    "Thoughts, gestures and narration are not speech. Action-only with null needs neither "
    "invented dialogue nor player approval. Emotional delivery remains free.\n"
)


def with_glossary(instruction: str) -> str:
    """Share the same definitions within each existing model instruction."""
    return instruction + GLOSSARY
