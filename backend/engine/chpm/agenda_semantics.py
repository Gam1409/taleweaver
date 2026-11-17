"""Shared meanings for speech-bound agenda codes, not world-action status."""

GLOSSARY = """
AGENDA CODES: null=immediate/ordered acts, silent/private intent or no change.
goal=ongoing aim; commitment=ongoing undertaking; withdraw=cancel; report_done=claim done, not world fact.
Non-null needs OWN SPEECH now (no stock phrase), never thoughts/gestures/narration.
Closures: text=ACTIVE OWNED TEXT, not dialogue; entry_id=ACTIVE ID.
"""


def with_glossary(instruction: str) -> str:
    """Share the same definitions within each existing model instruction."""
    return instruction + GLOSSARY
