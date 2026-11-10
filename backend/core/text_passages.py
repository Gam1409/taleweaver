"""Assign bounded references to unchanged contiguous source text, without interpretation."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Passage:
    start: int
    end: int
    text: str


def spans(text: str) -> dict[str, Passage]:
    result = {}
    number = 0
    for match in re.finditer(r'[^\n]+?(?:[.!?。！？]["”»]?(?=\s|$)|(?=\n)|$)', text):
        for offset in range(0, len(match[0]), 600):
            raw = match[0][offset : offset + 600]
            key = f"p{number}"
            number += 1
            if not raw.strip():
                continue
            start = match.start() + offset + len(raw) - len(raw.lstrip())
            end = match.start() + offset + len(raw.rstrip())
            result[key] = Passage(start, end, text[start:end])
    return result


def index(text: str) -> dict[str, str]:
    return {key: passage.text for key, passage in spans(text).items()}
