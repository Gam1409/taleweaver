"""Bounded process-local operational counters. Never retain prompts or story content."""

from collections import Counter
from threading import Lock

_lock = Lock()
_recall: Counter = Counter()
_staging: Counter = Counter()


def record_recall(metrics: dict, method: str) -> None:
    with _lock:
        _recall["projections"] += 1
        _recall["lexical_only"] += int(method == "sql_lexical")
        _recall["zero_hits"] += int(metrics.get("ranked", 0) == 0)
        for key in ("candidates", "ranked", "selected", "duplicates", "budget_skips"):
            _recall[key] += metrics.get(key, 0)


def record_staging(result: dict, proposed: int) -> None:
    """Count completed reconciliations, not API/model failures or skipped turns."""
    rejected = int(result.get("rejected", 0))
    with _lock:
        _staging["reconciliations"] += 1
        _staging["proposed_deltas"] += proposed
        _staging["rejected_deltas"] += rejected
        ready = result.get("status") == "ready"
        _staging["fail_closed_turns"] += int(not ready)
        _staging["partial_turns"] += int(ready and rejected > 0)
        _staging["ready_turns"] += int(ready)


def snapshot() -> dict:
    with _lock:
        return {
            "scope": "Current server process; counters reset on restart",
            "recall": dict(_recall),
            "staging": dict(_staging),
        }
