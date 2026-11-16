"""Extractive episodic recall: old details need a cue, never a new evidence root."""

import math
import re
from collections import Counter
from dataclasses import dataclass

from backend.engine.chpm.host_state import Mind, Source, fingerprint

POLICY = "extractive-episodes-v1"
EPISODE_SIZE = 16
RECALL_LIMIT = 3
FRAGMENT_CHARS = 300


@dataclass(frozen=True)
class Recollection:
    record_id: str
    source: Source
    fragment: str
    episode_id: str


def _words(text: str) -> set[str]:
    return {word for word in re.findall(r"[^\W_]+", text.casefold()) if len(word) >= 3}


def recall(
    mind: Mind, available: list[tuple[str, Source]], query: str
) -> tuple[list[Recollection], dict]:
    older = available[:-6]
    episodes = [older[index : index + EPISODE_SIZE] for index in range(0, len(older), EPISODE_SIZE)]
    tokens = [_words(source.text) for _, source in older]
    frequencies = Counter(word for words in tokens for word in words)
    cues = _words(query)
    # Common words cannot make every old episode relevant. This is a lexical
    # retrieval policy, not a probability of truth or a psychological salience score.
    if len(older) >= 4:
        cues = {cue for cue in cues if frequencies[cue] <= len(older) / 2}
    ranked = []
    for index, (record_id, source) in enumerate(older):
        hits = cues & tokens[index]
        if not hits:
            continue
        score = sum(math.log1p(len(older) / frequencies[word]) for word in hits)
        ranked.append((score, index, record_id, source, hits))
    chosen = sorted(ranked, key=lambda item: (-item[0], -item[1]))[:RECALL_LIMIT]
    results = [
        Recollection(
            record_id,
            source,
            _fragment(source.text, hits),
            fingerprint(
                {
                    "scope": mind.genesis.scope.model_dump(),
                    "sources": [key for key, _ in episodes[index // EPISODE_SIZE]],
                }
            ),
        )
        for _, index, record_id, source, hits in chosen
    ]
    return results, {
        "policy": POLICY,
        "retrieval_mode": "lexical",
        "older_sources": len(older),
        "episode_count": len(episodes),
        "matched_sources": len(ranked),
        "recalled_sources": len(results),
        "omitted_matches": max(0, len(ranked) - len(results)),
        "detail": "extractive_fragments",
        "new_evidence": False,
    }


def _fragment(text: str, cues: set[str]) -> str:
    # Regex match spans refer to original Unicode offsets, unlike offsets into
    # casefolded strings (which can change length).
    match = next((m for m in re.finditer(r"[^\W_]+", text) if m.group().casefold() in cues), None)
    start = max(0, (match.start() if match else 0) - 80)
    return text[start : start + FRAGMENT_CHARS]
