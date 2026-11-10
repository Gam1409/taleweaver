"""Assign bounded references to unchanged contiguous source text, without interpretation."""

import re


def index(text: str) -> dict[str, str]:
    # Segmentation assigns references, never speaker identity or factual status.
    pieces = re.findall(r'[^\n]+?(?:[.!?。！？]["”»]?(?=\s|$)|(?=\n)|$)', text)
    chunks = [
        piece[start : start + 600].strip()
        for piece in pieces
        for start in range(0, len(piece), 600)
    ]
    return {f"p{number}": chunk for number, chunk in enumerate(chunks) if chunk}
