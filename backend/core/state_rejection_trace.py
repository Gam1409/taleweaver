"""Context-owned, opt-in full evidence packets for rejected or unconfirmed state."""

from __future__ import annotations

import asyncio
import hashlib
import json
import platform
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import uuid4
from weakref import WeakSet

from backend.core.config import settings
from backend.core.diagnostic_detail import SECRET_KEYS, entries, operational_message, value
from backend.core.diagnostic_failures import failure_details
from backend.core.state_rejection_storage import write_packet

if TYPE_CHECKING:
    from backend.core.system_diagnostics import DiagnosticService

MAX_CAPTURE_BYTES = 50 * 1024 * 1024
MAX_OVERFLOW_SAMPLES = 16
MAX_REASON_SUMMARIES = 256
MAX_REASON_CHARS = 4096
TRACE_SCHEMA_VERSION = 1
_SECRET_NAMES = {re.sub(r"[^a-z0-9]", "", key) for key in SECRET_KEYS}
_current: ContextVar[Capture | None] = ContextVar("state_rejection_capture", default=None)
_captures: WeakSet[Capture] = WeakSet()
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*")
_URL_CREDENTIAL = re.compile(
    r"(?<![A-Za-z0-9+.-])([A-Za-z][A-Za-z0-9+.-]{0,31}://)[^\s/@:]+:[^\s/@]+@"
)


def _clean(item: Any) -> Any:
    if isinstance(item, str):
        text = _BEARER.sub("Bearer [credential excluded]", item)
        return operational_message(_URL_CREDENTIAL.sub(r"\1[credential excluded]@", text))
    if isinstance(item, dict):
        return {
            key: _clean(part)
            for key, part in item.items()
            if re.sub(r"[^a-z0-9]", "", key.lower()) not in _SECRET_NAMES
        }
    if isinstance(item, list):
        return [_clean(part) for part in item]
    return item


def _context_identity() -> tuple[int, int | None]:
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    return threading.get_ident(), id(task) if task is not None else None


def _reason_summary(domain: str, reason_code: str, reason: str) -> dict:
    payload = _clean(value({"domain": domain, "reason_code": reason_code, "reason": reason}))
    summary: dict[str, Any] = {}
    truncated = {}
    for key, part in payload.items():
        text = part if isinstance(part, str) else "[unavailable]"
        summary[key] = text[:MAX_REASON_CHARS]
        if len(text) > MAX_REASON_CHARS:
            truncated[key] = {
                "characters": len(text),
                "sha256": hashlib.sha256(text.encode()).hexdigest(),
            }
    if truncated:
        summary["truncated_fields"] = truncated
    return summary


@dataclass(eq=False)
class Capture:
    owner: DiagnosticService
    epoch: int
    context: dict
    context_identity: tuple[int, int | None] = field(default_factory=_context_identity)
    trace_id: str = field(default_factory=lambda: uuid4().hex)
    rows: list[dict] = field(default_factory=list)
    bytes: int = 0
    rejected_count: int = 0
    closed: bool = False
    overflow_events: int = 0
    overflow_bytes: int = 0
    overflow_samples: list[dict] = field(default_factory=list)
    rejection_summaries: list[dict] = field(default_factory=list)

    def discard(self) -> None:
        self.closed = True
        self.rows.clear()
        self.overflow_samples.clear()
        self.rejection_summaries.clear()

    def active(self) -> bool:
        return (
            not self.closed
            and self.owner.enabled
            and self.owner.state_failure_traces
            and self.epoch == self.owner.detail_epoch
        )

    def add(self, event: str, payload: dict, context: dict) -> None:
        sanitized = _clean(value(payload))
        context = {
            **context,
            **{key: self.context.get(key) for key in ("session_id", "turn_id", "operation")},
        }
        parts = [
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": event,
                **context,
                **part,
            }
            for part in entries(sanitized)
        ]
        serialized = json.dumps(parts, ensure_ascii=True, allow_nan=False).encode()
        if self.bytes + len(serialized) > MAX_CAPTURE_BYTES:
            self.overflow_events += 1
            self.overflow_bytes += len(serialized)
            if len(self.overflow_samples) < MAX_OVERFLOW_SAMPLES:
                self.overflow_samples.append(
                    {
                        "event": event,
                        "bytes": len(serialized),
                        "sha256": hashlib.sha256(serialized).hexdigest(),
                    }
                )
            return
        self.rows.extend(parts)
        self.bytes += len(serialized)


def invalidate(owner: DiagnosticService) -> None:
    """Called under the owner's lock so disabling immediately releases all buffers."""
    for capture in list(_captures):
        if capture.owner is owner:
            capture.discard()


def record(owner: DiagnosticService, event: str, payload: dict, context: dict) -> None:
    """Buffer existing detailed hooks only for the active operation in this context."""
    capture = _current.get()
    if capture is not None and capture.owner is owner and capture.active():
        capture.add(event, payload, context)


def _finish(capture: Capture) -> None:
    owner = capture.owner
    with owner._lock:
        if not capture.active() or not capture.rejected_count:
            capture.discard()
            return
        rows = [
            {
                "event": "state.trace.started",
                "trace_id": capture.trace_id,
                "schema_version": TRACE_SCHEMA_VERSION,
                "app_version": settings.APP_VERSION,
                "python_version": platform.python_version(),
                "context": _clean(value(capture.context)),
            },
            *capture.rows,
            {
                "event": "state.trace.ended",
                "trace_id": capture.trace_id,
                "rejected_count": capture.rejected_count,
                "rejection_summaries": capture.rejection_summaries,
                "omitted_rejection_summaries": max(
                    0, capture.rejected_count - len(capture.rejection_summaries)
                ),
                "capture_overflow": {
                    "omitted_events": capture.overflow_events,
                    "omitted_bytes": capture.overflow_bytes,
                    "samples": capture.overflow_samples,
                    "max_capture_bytes": MAX_CAPTURE_BYTES,
                },
            },
        ]
        try:
            write_packet(owner.directory, rows)
        except Exception:
            owner.write_failed = True
        finally:
            capture.discard()


def reject(domain: str, reason_code: str, reason: str, **details: object) -> None:
    """Observe an explicit rejected/unconfirmed outcome without changing execution."""
    from backend.core.system_diagnostics import service

    with service._lock:
        if not service.enabled or not service.state_failure_traces:
            return
        capture = _current.get()
        if capture is not None and not capture.active():
            return
        if capture is None:
            with scope(**service.current_context()):
                reject(domain, reason_code, reason, **details)
            return
        try:
            capture.rejected_count += 1
            if len(capture.rejection_summaries) < MAX_REASON_SUMMARIES:
                capture.rejection_summaries.append(_reason_summary(domain, reason_code, reason))
            capture.add(
                "state.rejected",
                {
                    "domain": domain,
                    "reason_code": reason_code,
                    "reason": reason,
                    "details": details,
                },
                service.current_context(),
            )
        except Exception:
            service.write_failed = True


def _failure(error: BaseException) -> None:
    interrupted = not isinstance(error, Exception)
    failure = failure_details(error)
    reject(
        "state",
        "operation_interrupted" if interrupted else "operation_failed",
        "The operation was interrupted." if interrupted else "The operation failed.",
        error=failure["error"],
        validation_reason=failure.get("failure_reason") if isinstance(error, ValueError) else None,
    )


@contextmanager
def scope(
    *,
    session_id: str | None = None,
    turn_id: str | None = None,
    operation: str = "state_update",
    reuse_parent: bool = False,
    **context: object,
) -> Iterator[None]:
    """Retain full evidence only until an explicit failure or scope interruption."""
    from backend.core.system_diagnostics import service

    capture = None
    marker = None
    reuse = False
    with service._lock:
        if service.enabled and service.state_failure_traces:
            existing = _current.get()
            same_session = (
                session_id is None
                or existing is None
                or existing.context.get("session_id") == session_id
            )
            same_turn = (
                turn_id is None or existing is None or existing.context.get("turn_id") == turn_id
            )
            if (
                existing is not None
                and existing.active()
                and same_session
                and same_turn
                and (reuse_parent or existing.context.get("operation") == operation)
                and existing.context_identity == _context_identity()
            ):
                reuse = True
            else:
                fields = {**service.current_context(), **context, "operation": operation}
                fields.update(session_id=session_id or fields.get("session_id"), turn_id=turn_id)
                capture = Capture(service, service.detail_epoch, fields)
                _captures.add(capture)
                marker = _current.set(capture)
    if reuse:
        yield
        return
    try:
        yield
    except BaseException as error:
        if capture is not None:
            try:
                _failure(error)
            except Exception:
                service.write_failed = True
        raise
    finally:
        if marker is not None:
            _current.reset(marker)
        if capture is not None:
            try:
                _finish(capture)
            except Exception:
                capture.discard()
                service.write_failed = True
