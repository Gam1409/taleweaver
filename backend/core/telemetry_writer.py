"""Bounded, rotating diagnostic writes outside the event loop."""

import atexit
import logging
import logging.handlers
import queue
import threading
from pathlib import Path

_queue: queue.Queue[tuple[str, str] | None] = queue.Queue(maxsize=256)
_lock = threading.Lock()
_started = threading.Event()


def _run() -> None:
    handlers: dict[str, logging.Handler] = {}
    while (item := _queue.get()) is not None:
        path, text = item
        try:
            if path not in handlers:
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                handlers[path] = logging.handlers.RotatingFileHandler(
                    path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
                )
            handlers[path].emit(logging.LogRecord("telemetry", logging.INFO, "", 0, text, (), None))
        except OSError:
            logging.getLogger(__name__).warning("Diagnostic file write failed")
        finally:
            _queue.task_done()
    for handler in handlers.values():
        handler.close()


def enqueue(path: str, text: str) -> None:
    with _lock:
        if not _started.is_set():
            threading.Thread(target=_run, name="telemetry-writer", daemon=True).start()
            _started.set()
    try:
        _queue.put_nowait((path, text))
    except queue.Full:
        # Diagnostics must never block gameplay or grow without bound.
        logging.getLogger(__name__).warning("Diagnostic queue full; event dropped")


@atexit.register
def _finish() -> None:
    if _started.is_set():
        _queue.join()
        _queue.put(None)
