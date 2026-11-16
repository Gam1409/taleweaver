"""Bounded cache for background indexing; foreground evidence is always reread.

The durable desired revision and epoch invalidate normal writes/rewinds. A stale
background entry can only delay index freshness: candidate validation and summary
publication still read canonical SQL sources independently.
"""

import time
from collections import OrderedDict
from typing import Any

_MAX_CHARS = 8_000_000
_TTL = 120.0
_cache: OrderedDict[tuple[str, str, int, int], tuple[float, int, list[Any]]] = OrderedDict()


def get(key: tuple[str, str, int, int]) -> list[Any] | None:
    entry = _cache.get(key)
    if entry is None:
        return None
    if time.monotonic() - entry[0] > _TTL:
        _cache.pop(key, None)
        return None
    _cache.move_to_end(key)
    return entry[2]


def put(key: tuple[str, str, int, int], documents: list[Any]) -> None:
    size = sum(len(doc.text) for doc in documents)
    if size > _MAX_CHARS:
        return
    for previous in list(_cache):
        if previous[:2] == key[:2]:
            del _cache[previous]
    while _cache and (
        len(_cache) >= 4 or sum(item[1] for item in _cache.values()) + size > _MAX_CHARS
    ):
        _cache.popitem(last=False)
    _cache[key] = (time.monotonic(), size, documents)


def clear() -> None:
    _cache.clear()
