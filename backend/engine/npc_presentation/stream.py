"""Hide an optional service footer before any token reaches story, audio or memory."""

OPEN = "<npc-state>"
CLOSE = "</npc-state>"
MAX_FOOTER = 10000


class FooterStream:
    def __init__(self) -> None:
        self.pending = ""
        self.footer = ""
        self.started = False
        self.complete = False
        self.overflow = False

    def feed(self, text: str) -> str:
        if self.complete:
            return ""
        if self.started:
            self._capture(text)
            return ""
        self.pending += text
        index = self.pending.lower().find(OPEN)
        if index >= 0:
            visible = self.pending[:index]
            tail = self.pending[index + len(OPEN) :]
            self.pending = ""
            self.started = True
            self._capture(tail)
            return visible
        keep = self._partial_open()
        visible = self.pending[:-keep] if keep else self.pending
        self.pending = self.pending[-keep:] if keep else ""
        return visible

    def _partial_open(self) -> int:
        lower = self.pending.lower()
        return next(
            (
                size
                for size in range(min(len(lower), len(OPEN) - 1), 0, -1)
                if lower.endswith(OPEN[:size])
            ),
            0,
        )

    def _capture(self, text: str) -> None:
        if self.overflow:
            return
        self.footer += text
        index = self.footer.lower().find(CLOSE)
        if index >= 0:
            self.footer = self.footer[:index]
            self.complete = True
        if len(self.footer) > MAX_FOOTER:
            self.footer = ""
            self.overflow = True

    def finish(self) -> str:
        # Preserve ordinary angle brackets; hide recognizably truncated service tags.
        visible = self.pending if len(self.pending) < 4 else ""
        self.pending = ""
        return visible


def split(text: str) -> tuple[str, str | None]:
    stream = FooterStream()
    visible = stream.feed(text) + stream.finish()
    return visible, stream.footer if stream.complete and not stream.overflow else None
