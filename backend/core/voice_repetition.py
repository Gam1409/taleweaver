"""Limit vocal runs in output and prevent old delivery cues becoming style examples."""

import re

from backend.core.voice_tags import VOCAL_BURST_SET, VOICE_TAG_SET

_BURSTS = VOICE_TAG_SET | VOCAL_BURST_SET
_HISTORY_CUE = re.compile(r"<([^<>\n]{1,64})>")
MAX_RUN_TAGS = 8
MAX_SAME_TAG = 2
MAX_TAG_CHARS = 64


class VoiceRepetitionFilter:
    """State survives token boundaries; actual speech starts a new vocal run."""

    def __init__(self) -> None:
        self.pending = ""
        self.counts: dict[str, int] = {}
        self.total = 0

    def _text(self, text: str) -> str:
        if any(char.isalnum() for char in text):
            self.counts.clear()
            self.total = 0
        return text

    def _tag(self, tag: str) -> str:
        name = tag[1:-1].strip().lower()
        if name not in _BURSTS:
            return self._text(tag)
        count = self.counts.get(name, 0)
        if count >= MAX_SAME_TAG or self.total >= MAX_RUN_TAGS:
            return ""
        self.counts[name] = count + 1
        self.total += 1
        return tag

    def feed(self, text: str) -> str:
        self.pending += text
        result = []
        while self.pending:
            start = self.pending.find("<")
            if start < 0:
                result.append(self._text(self.pending))
                self.pending = ""
                break
            result.append(self._text(self.pending[:start]))
            self.pending = self.pending[start:]
            end = self.pending.find(">")
            if end < 0 and len(self.pending) <= MAX_TAG_CHARS:
                break
            if end < 0 or end >= MAX_TAG_CHARS:
                result.append(self._text(self.pending[:1]))
                self.pending = self.pending[1:]
                continue
            result.append(self._tag(self.pending[: end + 1]))
            self.pending = self.pending[end + 1 :]
        return "".join(result)

    def finish(self) -> str:
        tail, self.pending = self.pending, ""
        return tail


def clean_voice_repetition(text: str) -> str:
    cleaner = VoiceRepetitionFilter()
    return cleaner.feed(text) + cleaner.finish()


def clean_voice_history(messages: list[dict]) -> list[dict]:
    """Omit old inline delivery cues from model input, preserving prose and tone tags."""
    cleaned = []
    for message in messages:
        if message.get("role") != "assistant" or not isinstance(message.get("content"), str):
            cleaned.append(message)
            continue
        content = strip_historical_voice_cues(message["content"])
        # Some providers reject empty text messages; preserve structured tool responses.
        if content.strip() or message.get("tool_calls") or message.get("function_call"):
            cleaned.append({**message, "content": content})
    return cleaned


def strip_historical_voice_cues(text: str) -> str:
    """Remove only known angle-bracket cues; keep emotional [tags] and unknown markup."""
    return _HISTORY_CUE.sub(
        lambda match: "" if match[1].strip().lower() in _BURSTS else match[0], text
    )
