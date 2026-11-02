"""Lossless cold journal chunks, leaving a bounded mutable working history.

Chunks remain in the portable NPC metadata so exports, checkpoints and forks
carry their provenance without an external-file dependency.
"""

import base64
import json
import zlib
from copy import deepcopy
from typing import Any

WORKING_ENTRIES = 128
MAX_CHUNK_BYTES = 2 * 1024 * 1024


def expanded(journal: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(journal)
    entries = []
    for chunk in result.pop("archive", []):
        if not isinstance(chunk, str) or len(chunk) > MAX_CHUNK_BYTES * 2:
            raise ValueError("Journal archive chunk exceeds its size limit.")
        decoder = zlib.decompressobj()
        decoded = decoder.decompress(base64.b64decode(chunk, validate=True), MAX_CHUNK_BYTES + 1)
        if len(decoded) > MAX_CHUNK_BYTES or not decoder.eof or decoder.unused_data:
            raise ValueError("Invalid or oversized journal archive chunk.")
        records = json.loads(decoded)
        if not isinstance(records, list) or len(records) > WORKING_ENTRIES:
            raise ValueError("Invalid journal archive records.")
        entries.extend(records)
    result["entries"] = entries + result.get("entries", [])
    return result


def compact(journal: dict[str, Any]) -> dict[str, Any]:
    result = dict(journal)
    entries = list(result.get("entries") or [])
    archives = list(result.get("archive") or [])
    while len(entries) > WORKING_ENTRIES * 2:
        count = WORKING_ENTRIES
        chunk, entries = entries[:count], entries[count:]
        if len(json.dumps(chunk, ensure_ascii=False).encode()) > MAX_CHUNK_BYTES:
            raise ValueError("Journal archive records exceed their size limit.")
        archives.append(
            base64.b64encode(zlib.compress(json.dumps(chunk, ensure_ascii=False).encode())).decode()
        )
    result.update(entries=entries, archive=archives)
    return result
