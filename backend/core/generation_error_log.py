"""Persistent server-side log for failures during adventure generation.

Every failure gets a short error id that is written to
``<log dir>/generation_errors.log`` together with the full traceback and any LLM
diagnostics (model, token budget, actual usage). The same id is shown in the
generation view so a user report can be matched to the server log entry.
Unlike the LLM telemetry log this file is always written.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import traceback
import uuid
from logging.handlers import RotatingFileHandler
from typing import Any, Optional

from backend.core.config import settings

logger = logging.getLogger(__name__)

LOG_FILE_NAME = "generation_errors.log"
_MAX_LOG_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 5
_MAX_CREATION_ERROR_LENGTH = 500

# Lazily created file logger, keyed by "logger" (a dict avoids a module-level `global`).
_state: dict[str, logging.Logger] = {}


def _log_dir() -> str:
    return settings.LLM_LOG_DIR or os.path.join(settings.DATA_DIR, "logs")


def _get_file_logger() -> logging.Logger:
    """Dedicated non-propagating logger with a rotating file handler (created lazily)."""
    cached = _state.get("logger")
    if cached is not None:
        return cached
    os.makedirs(_log_dir(), exist_ok=True)
    handler = RotatingFileHandler(
        os.path.join(_log_dir(), LOG_FILE_NAME),
        maxBytes=_MAX_LOG_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    file_logger = logging.getLogger("taleweaver.generation_errors")
    file_logger.setLevel(logging.ERROR)
    file_logger.propagate = False
    for stale in list(file_logger.handlers):
        file_logger.removeHandler(stale)
        stale.close()
    file_logger.addHandler(handler)
    _state["logger"] = file_logger
    return file_logger


def _format_record(record: dict[str, Any], trace: str) -> str:
    header = json.dumps(record, ensure_ascii=False, default=str)
    return f"{header}\n{trace.rstrip()}\n{'-' * 80}"


def record_generation_error(
    exc: BaseException,
    *,
    stage: str,
    template_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> dict[str, Any]:
    """Writes the failure to the server log and returns a ``type: error`` log entry.

    The returned entry is safe to show to the user: it contains the message, the
    error id and LLM diagnostics, but never the traceback. Never raises.
    """
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    error_id = uuid.uuid4().hex[:10]
    details: dict[str, Any] = {
        "error_id": error_id,
        "stage": stage,
        "exception_type": type(exc).__name__,
        "server_log": LOG_FILE_NAME,
    }
    diagnostics = getattr(exc, "diagnostics", None)
    if isinstance(diagnostics, dict) and diagnostics:
        details["diagnostics"] = diagnostics

    message = str(exc) or type(exc).__name__
    record = {"timestamp": timestamp, "template_id": template_id, "user_id": user_id}
    record.update(details, message=message)
    trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    try:
        _get_file_logger().error(_format_record(record, trace))
    except OSError:
        logger.exception("Could not write generation error log entry %s", error_id)
    logger.error("Generation error %s (%s) for %s: %s", error_id, stage, template_id, message)

    return {"timestamp": timestamp, "type": "error", "content": message, "details": details}


def format_creation_error(entry: dict[str, Any]) -> str:
    """Short status text for ``creation_error`` (column limit 500); full text is in the log."""
    error_id = (entry.get("details") or {}).get("error_id", "?")
    text = f"[Error ID {error_id}] {entry.get('content', '')}"
    if len(text) <= _MAX_CREATION_ERROR_LENGTH:
        return text
    return text[: _MAX_CREATION_ERROR_LENGTH - 3] + "..."


def append_generation_log_entry(adventure: Any, entry: dict[str, Any]) -> None:
    """Appends an entry to the template's generation log (caller commits)."""
    logs = list(adventure.generation_logs or [])
    logs.append(entry)
    adventure.generation_logs = logs
