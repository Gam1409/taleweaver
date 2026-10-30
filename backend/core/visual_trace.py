"""Opt-in local visual diagnostics, isolated from ordinary logs and HTTP assets."""

import hashlib
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.core.config import settings

DIRECTORY = Path(__file__).resolve().parents[2] / "log" / "visual-traces"
MAX_FILES = 30
MAX_BYTES = 1024 * 1024
MAX_CONTENT = 100000
_context: ContextVar[dict | None] = ContextVar("visual_trace", default=None)
logger = logging.getLogger(__name__)
_active_paths: set[Path] = set()


def current_id() -> str | None:
    context = _context.get()
    return str(context["id"]) if context is not None else None


def record(stage: str, **values: Any) -> None:
    """Callers supply only stage data, never request options, headers or credentials."""
    context = _context.get()
    if context is None or context["failed"]:
        return
    fields = {}
    for key, value in values.items():
        serialized = json.dumps(value, ensure_ascii=False, default=str)
        fields[key] = {
            "chars": len(serialized),
            "sha256": hashlib.sha256(serialized.encode()).hexdigest(),
        }
        if settings.VISUAL_TRACE_CONTENT_ENABLED:
            fields[key]["content"] = serialized[:MAX_CONTENT]
            fields[key]["truncated"] = len(serialized) > MAX_CONTENT
    entry = {
        "trace_id": context["id"],
        "stage": stage,
        "elapsed_ms": round((time.monotonic() - context["start"]) * 1000),
        "fields": fields,
    }
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    if context["bytes"] + len(line.encode()) > MAX_BYTES:
        return
    try:
        with context["path"].open("a", encoding="utf-8") as handle:
            handle.write(line)
        context["bytes"] += len(line.encode())
    except OSError:
        context["failed"] = True
        logger.warning("Visual trace storage unavailable; generation continues.")


def traced(method: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    @wraps(method)
    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        if not settings.VISUAL_TRACE_ENABLED:
            return await method(*args, **kwargs)
        trace_id = uuid4().hex
        context: dict[str, Any] = {
            "id": trace_id,
            "start": time.monotonic(),
            "bytes": 0,
            "failed": False,
        }
        try:
            DIRECTORY.mkdir(parents=True, exist_ok=True, mode=0o700)
            paths = sorted(DIRECTORY.glob("*.jsonl"), key=lambda path: path.stat().st_mtime)
            for path in paths[: max(0, len(paths) - MAX_FILES + 1)]:
                if path not in _active_paths:
                    path.unlink(missing_ok=True)
            context["path"] = DIRECTORY / f"{trace_id}.jsonl"
            fd = os.open(context["path"], os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        except OSError:
            logger.warning("Visual trace storage unavailable; generation continues.")
            return await method(*args, **kwargs)
        _active_paths.add(context["path"])
        token = _context.set(context)
        try:
            record("started")
            result = await method(*args, **kwargs)
            record("completed")
            return result
        except BaseException as exc:
            record("failed", error_type=type(exc).__name__)
            raise
        finally:
            _context.reset(token)
            _active_paths.discard(context["path"])

    return wrapped
