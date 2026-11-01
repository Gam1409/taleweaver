"""Bounded process-local operational counters. Never retain prompts or story content."""

from collections import Counter
from threading import Lock

_lock = Lock()
_recall: Counter = Counter()


def record_recall(metrics: dict, method: str) -> None:
    with _lock:
        _recall["projections"] += 1
        _recall["lexical_only"] += int(method == "sql_lexical")
        _recall["zero_hits"] += int(metrics.get("ranked", 0) == 0)
        for key in ("candidates", "ranked", "selected", "duplicates", "budget_skips"):
            _recall[key] += metrics.get(key, 0)


def snapshot() -> dict:
    with _lock:
        return {
            "scope": "Current server process; counters reset on restart",
            "recall": dict(_recall),
        }
