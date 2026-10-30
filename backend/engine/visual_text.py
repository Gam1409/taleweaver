"""Remove delivery-only cues from a copy of text used for image preparation."""

import re

from backend.core.voice_tags import VOCAL_BURST_SET

_TAGS = VOCAL_BURST_SET | {
    "giggles",
    "laughs",
    "sighs",
    "gasps",
    "pauses",
    "pause",
    "dramatic pause",
}
_MARKER = re.compile(r"<([^<>\n]{1,64})>|\[([^\[\]\n]{1,64})\]")


def visual_text(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        tag = match.group(1) or match.group(2)
        return " " if tag.strip().lower() in _TAGS else match.group(0)

    return re.sub(r"[ \t]{2,}", " ", _MARKER.sub(replace, text)).strip()
