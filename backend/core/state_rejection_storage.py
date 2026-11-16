"""Private generated trace packets with bounded retention in the diagnostic directory."""

import json
import os
import re
from pathlib import Path
from uuid import uuid4

from backend.utils.path_security import ensure_within_base_dir

MAX_TRACE_FILES = 5
MAX_TOTAL_BYTES = 250 * 1024 * 1024
_NAME = re.compile(r"state-rejection-[a-f0-9]{32}\.jsonl")


def _path(directory: Path, name: str) -> Path:
    return Path(ensure_within_base_dir(str(directory / name), str(directory)))


def _retention(directory: Path, required: int) -> dict:
    files = [
        path
        for path in directory.glob("state-rejection-*.jsonl")
        if _NAME.fullmatch(path.name) and not path.is_symlink()
    ]
    files.sort(key=lambda path: (path.stat().st_mtime_ns, path.name))
    total = sum(path.stat().st_size for path in files)
    removed_count = removed_bytes = 0
    while files and (len(files) >= MAX_TRACE_FILES or total + required > MAX_TOTAL_BYTES):
        path = files.pop(0)
        size = path.stat().st_size
        _path(directory, path.name).unlink()
        total -= size
        removed_count += 1
        removed_bytes += size
    return {"removed_files": removed_count, "removed_bytes": removed_bytes}


def write_packet(directory: Path, rows: list[dict]) -> None:
    """Publish a complete packet, cleaning partial writes without exposing file paths."""
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    rows[-1]["retention"] = _retention(
        directory, sum(len(json.dumps(row, ensure_ascii=True).encode()) + 1 for row in rows) + 256
    )
    identity = uuid4().hex
    temporary = _path(directory, f".state-rejection-{identity}.tmp")
    target = _path(directory, f"state-rejection-{identity}.jsonl")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            for row in rows:
                output.write(json.dumps(row, ensure_ascii=True, allow_nan=False) + "\n")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
