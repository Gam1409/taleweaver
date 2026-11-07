"""Contiguous, query-focused excerpts with offsets into the canonical document."""

import re
from collections import Counter

from backend.engine.memory_rag.ranking import tokens


def excerpt(text: str, limit: int, query: str) -> tuple[int, int]:
    if len(text) <= limit:
        return 0, len(text)
    words = list(re.finditer(r"[^\W_]+", text))
    frequencies = Counter(word.group().casefold() for word in words)
    terms = tokens(query)
    matches = [word for word in words if word.group().casefold() in terms]
    if not matches:
        return 0, limit
    anchor = max(matches, key=lambda word: 1 / frequencies[word.group().casefold()])
    start = max(0, min(len(text) - limit, anchor.start() - limit // 3))
    boundaries = list(re.finditer(r"[.!?\n](?:\s|$)", text))
    left = max((m.end() for m in boundaries if m.end() <= anchor.start()), default=0)
    right = next((m.end() for m in boundaries if m.start() >= anchor.end()), len(text))
    if right - left <= limit:
        start = max(0, min(left, max(start, right - limit)))
    return start, min(len(text), start + limit)


def body(text: str, core: bool) -> tuple[str, int]:
    if not core:
        return text, 0
    description = text.partition("\nEvidence:")[0]
    header, separator, value = description.partition("): ")
    return (value, len(header) + len(separator)) if separator else (description, 0)
