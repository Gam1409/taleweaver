"""Explicit local model responses for the bounded proposal-correction contract."""

import json
from typing import Any


def corrections(*changes: tuple[str, Any]) -> str:
    return json.dumps(
        {"edits": [{"op": "replace", "path": path, "value": value} for path, value in changes]},
        ensure_ascii=False,
    )
