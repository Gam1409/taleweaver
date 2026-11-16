"""Explicit full-content records, lossless multipart payloads and credential-key exclusion."""

import hashlib
import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

PART_CHARS = 60000
_CREDENTIAL = re.compile(
    r"""(?i)(["']?(?:api[_ -]?key|authorization|password|access_token|refresh_token)["']?\s*(?:provided\s*)?[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;}]+)"""
)
SECRET_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "password",
        "access_token",
        "refresh_token",
        "encrypted_api_keys",
        "cookie",
        "set-cookie",
        "headers",
        "extra_headers",
        "token",
        "secret",
        "client_secret",
        "private_key",
        "credentials",
    }
)


def value(item: Any) -> Any:
    """Preserve story strings verbatim; never serialize arbitrary ORM objects or settings."""
    if item is None or isinstance(item, (str, int, float, bool)):
        return item
    if hasattr(item, "model_dump"):
        return value(item.model_dump(mode="json"))
    if is_dataclass(item) and not isinstance(item, type):
        return value(asdict(item))
    if isinstance(item, Mapping):
        return {
            str(key): value(part)
            for key, part in item.items()
            if str(key).lower() not in SECRET_KEYS
        }
    if isinstance(item, (list, tuple, set, frozenset)):
        values = sorted(item, key=str) if isinstance(item, (set, frozenset)) else item
        return [value(part) for part in values]
    return _scalar(item)


def _scalar(item: Any) -> Any:
    if isinstance(item, (date, datetime)):
        return item.isoformat()
    if isinstance(item, UUID):
        return str(item)
    return {"unserialized_type": type(item).__name__}


def entries(payload: dict) -> Iterator[dict]:
    content = value(payload)
    serialized = json.dumps(content, ensure_ascii=False, allow_nan=False)
    if len(serialized) <= PART_CHARS:
        yield {"detail": content}
        return
    group = uuid4().hex
    count = (len(serialized) + PART_CHARS - 1) // PART_CHARS
    digest = hashlib.sha256(serialized.encode()).hexdigest()
    for index in range(count):
        yield {
            "detail_group": group,
            "part": index + 1,
            "parts": count,
            "payload_sha256": digest,
            "payload_json_part": serialized[index * PART_CHARS : (index + 1) * PART_CHARS],
        }


def operational_message(text: str) -> str:
    """Redact connection credential syntax in engine log messages, not story payloads."""
    text = _CREDENTIAL.sub(r"\1[credential excluded]", text)
    return re.sub(r"\bsk-[A-Za-z0-9_-]{8,}", "[credential excluded]", text)
