"""Small deterministic value conversions for author blueprints."""

import json
import re
from typing import Any


def normalize_id(raw: str) -> str:
    clean = raw.replace("##", "").strip().strip("\"'").lstrip("@")
    return re.sub(r"[^A-Za-z0-9]+", "_", clean).strip("_").upper()


def text(raw: str) -> str:
    return raw.strip()


def boolean(raw: str) -> bool:
    value = raw.strip().lower()
    if value in {"yes", "true", "on", "1"}:
        return True
    if value in {"no", "false", "off", "0"}:
        return False
    raise ValueError("expected yes/no or true/false")


def integer(raw: str) -> int:
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise ValueError("expected a whole number") from exc


def ident_list(raw: str) -> list[str]:
    return [normalize_id(part) for part in raw.split(",") if part.strip()]


def json_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise ValueError("expected valid JSON for this structured field") from exc
