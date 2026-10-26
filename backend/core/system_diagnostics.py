"""Opt-in rotating operational metadata, separate from raw LLM telemetry."""

import json
import logging
import os
import sys
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import override
from uuid import uuid4

from backend.core.diagnostic_fields import EVENTS, safe_error, safe_fields

_context: ContextVar[dict | None] = ContextVar("system_diagnostic_context", default=None)
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 4


class MetadataHandler(logging.Handler):
    """Discard arbitrary log text, including preformatted SQL/provider exceptions."""

    def __init__(self, owner):
        super().__init__(logging.NOTSET)
        self.owner = owner

    def emit(self, record: logging.LogRecord) -> None:
        if not self.owner.enabled:
            return
        source = {
            "file": Path(record.pathname).name,
            "function": record.funcName,
            "line": record.lineno,
        }
        error = record.exc_info[1] if record.exc_info else None
        self.owner._write(
            "system.log",
            {
                "severity": logging.getLevelName(record.levelno),
                "source": source,
                "error": safe_error(error) if error is not None else None,
                **(_context.get() or {}),
            },
        )


class DiagnosticWriter(RotatingFileHandler):
    def __init__(self, owner):
        self.owner = owner
        super().__init__(
            owner.directory / "system-debug.jsonl",
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )

    @override
    def handleError(self, record):
        # Disk failures must neither fail gameplay nor dump a logging exception.
        self.owner.write_failed = True


class DiagnosticService:
    def __init__(self, directory: Path):
        self.directory = directory
        self.enabled = False
        self.write_failed = False
        self._writer = None
        self._capture = MetadataHandler(self)
        self._lock = threading.RLock()

    def status(self) -> dict:
        return {
            "enabled": self.enabled,
            "log_directory": "log",
            "retention_files": BACKUP_COUNT + 1,
            "write_error": "Diagnostic storage is unavailable." if self.write_failed else None,
        }

    @contextmanager
    def context(self, **fields):
        token = _context.set({**(_context.get() or {}), **safe_fields(fields)})
        try:
            yield
        finally:
            _context.reset(token)

    def initialize(self) -> None:
        try:
            data = json.loads((self.directory / ".system-debug.json").read_text())
            self.set_enabled(data.get("enabled") is True, persist=False)
        except FileNotFoundError:
            return
        except (OSError, ValueError, TypeError, AttributeError):
            self.write_failed = True

    def _save_setting(self, enabled: bool) -> None:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.directory / f".system-debug-{uuid4().hex}.tmp"
        try:
            temporary.write_text(json.dumps({"enabled": enabled}), encoding="utf-8")
            os.replace(temporary, self.directory / ".system-debug.json")
        finally:
            temporary.unlink(missing_ok=True)

    def set_enabled(self, enabled: bool, *, persist: bool = True) -> dict:
        with self._lock:
            writer = self._writer
            if enabled and writer is None:
                self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                writer = DiagnosticWriter(self)
                writer.setFormatter(logging.Formatter("%(message)s"))
            try:
                if persist:
                    self._save_setting(enabled)
            except OSError:
                if writer is not self._writer and writer is not None:
                    writer.close()
                raise
            self._writer = writer
            self.write_failed = False
            if enabled:
                self.enabled = True
                logging.getLogger().addHandler(self._capture)
                self.emit("diagnostics.enabled")
            else:
                self.emit("diagnostics.disabled")
                self.close()
            return self.status()

    def close(self) -> None:
        with self._lock:
            logging.getLogger().removeHandler(self._capture)
            self.enabled = False
            if self._writer is not None:
                self._writer.close()
                self._writer = None

    def emit(self, event: str, **fields) -> None:
        if not self.enabled or not isinstance(event, str) or event not in EVENTS:
            return
        data = {**(_context.get() or {}), **safe_fields(fields)}
        error = fields.get("error")
        if isinstance(error, BaseException):
            data["error"] = safe_error(error)
        frame = sys._getframe(1)
        data["source"] = {
            "file": Path(frame.f_code.co_filename).name,
            "function": frame.f_code.co_name,
            "line": frame.f_lineno,
        }
        self._write(event, data)

    def http_event(self, event: str, scope: dict, **fields) -> None:
        if not self.enabled or event not in EVENTS:
            return
        data = {**(_context.get() or {}), **safe_fields(fields)}
        route = scope.get("route")
        # The registered route pattern is code, never the user's path/query.
        data["route"] = getattr(route, "path", "<unmatched>")
        data.update(safe_fields(scope.get("path_params", {})))
        error = fields.get("error")
        if isinstance(error, BaseException):
            data["error"] = safe_error(error)
        self._write(event, data)

    def _write(self, event: str, data: dict) -> None:
        with self._lock:
            if not self.enabled or self._writer is None:
                return
            entry = {"timestamp": datetime.now(timezone.utc).isoformat(), "event": event, **data}
            record = logging.LogRecord(
                "system_diagnostics",
                logging.INFO,
                "",
                0,
                json.dumps(entry, ensure_ascii=True),
                (),
                None,
            )
            try:
                # Do not use logger propagation: this record is already sanitized.
                self._writer.emit(record)
            except OSError:
                self.write_failed = True


service = DiagnosticService(Path(__file__).resolve().parents[2] / "log")
