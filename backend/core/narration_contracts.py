"""Shared source and identity rules for player-facing narration."""

PLAYER_ACTION_ATTRIBUTION = """PLAYER ACTION ATTRIBUTION:
Credit a completed player action only when the player's actual contribution or
engine-approved outcome establishes that action and its actor. An offer, promise,
request, intention or invitation does not establish acceptance, movement or work.
When a successful outcome is confirmed but its actor is unspecified, describe the
outcome without assigning the work to the player. NPC speech and fictional thoughts
must not invent that attribution through thanks, praise, blame or recollection.
An explicitly attributed suspicion or character-supported deception remains a
fallible claim; it cannot establish a player action, consent or confirmed history.
An NPC may give directions, hold out an object or act independently; stop before
assuming the player follows those directions, takes the object or joins the work.
"""

DISPLAY_NAME_IDENTITY = (
    "Copy each supplied display name exactly in speaker labels, using a localized "
    "display name only when one is explicitly supplied. Do not invent a translation, "
    "transliteration or alternate spelling for a speaker label. Every character "
    "reference must keep the same person's identity; never substitute a "
    "similar-sounding name or switch between inconsistent name forms."
)
