"""Bound runaway vocal-tag runs without deleting speech or ordinary delivery cues."""

from backend.core.voice_tags import VOICE_TAG_SET

_BURSTS = VOICE_TAG_SET | {
    "cough",
    "sigh",
    "breath",
    "heavy breath",
    "laugh",
    "chuckle",
    "throat-clearing",
    "short pause",
    "long pause",
    "gasp",
    "groan",
}
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
    """Clean a copy of assistant history only; persisted messages are not rewritten."""
    return [
        {**message, "content": clean_voice_repetition(message["content"])}
        if message.get("role") == "assistant" and isinstance(message.get("content"), str)
        else message
        for message in messages
    ]
