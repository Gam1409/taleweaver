"""Thread-safe admission with a durable crash/uncertain-request fence.

The journal stores hashes and request tokens only, never URLs, credentials or text.
It is runtime coordination, not world state. One backend worker owns this file.
"""

import hashlib
import json
import logging
import os
import threading
import time
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

logger = logging.getLogger(__name__)

background_call: ContextVar[bool] = ContextVar("inference_background", default=False)


class InferenceUncertainError(ValueError):
    """The server may still be computing; a retry must not bypass its fence."""


class InferenceQueueError(ValueError):
    """Admission failed before a remote request was submitted."""


def endpoint_key(url: str) -> str:
    """Group API aliases and model roles on the same origin, without DNS lookups."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise InferenceQueueError("Inference reservation requires a valid server URL.")
    host = parsed.hostname.lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        host = "loopback"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return hashlib.sha256(f"{parsed.scheme}://{host}:{port}".encode()).hexdigest()


@dataclass(frozen=True)
class Ticket:
    key: str
    token: str
    background: bool


class Registry:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.RLock()
        self.waiters: list[Ticket] = []
        self.active: set[str] = set()
        self.records: dict[str, dict] | None = None

    def _load(self) -> dict[str, dict]:
        if self.records is not None:
            return self.records
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            data = {}
        if not isinstance(data, dict) or any(
            not isinstance(row, dict)
            or not isinstance(row.get("token"), str)
            or not isinstance(row.get("started"), (int, float))
            for row in data.values()
        ):
            raise InferenceQueueError("Inference journal is invalid; restore a valid backup.")
        self.records = data
        return data

    def _write(self, records: dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(records, handle)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(self.path)
        self.records = records

    def enqueue(self, key: str) -> Ticket:
        with self.lock:
            if len(self.waiters) >= 256:
                raise InferenceQueueError("Inference queue is full; try again later.")
            ticket = Ticket(key, str(uuid4()), background_call.get())
            self.waiters.append(ticket)
            return ticket

    def forget(self, ticket: Ticket) -> None:
        with self.lock:
            if ticket in self.waiters:
                self.waiters.remove(ticket)

    def try_acquire(self, ticket: Ticket, *, background_ready: bool = True) -> bool:
        with self.lock:
            records = self._load()
            current = records.get(ticket.key)
            if current and current["token"] not in self.active:
                raise InferenceUncertainError(
                    "The AI server may still be processing a previous request. "
                    "Ask the administrator to check Inference queue before retrying."
                )
            if current or (ticket.background and not background_ready):
                return False
            eligible = sorted(
                (item for item in self.waiters if item.key == ticket.key),
                key=lambda item: item.background,
            )
            if not eligible or eligible[0] != ticket:
                return False
            if len(records) >= 256:
                raise InferenceQueueError("Too many unresolved inference servers.")
            self._write({**records, ticket.key: {"token": ticket.token, "started": time.time()}})
            self.active.add(ticket.token)
            logger.info("Inference admitted: endpoint=%s request=%s", ticket.key, ticket.token)
            self.waiters.remove(ticket)
            return True

    def finish(self, ticket: Ticket, *, certain: bool) -> None:
        with self.lock:
            records = self._load()
            current = records.get(ticket.key)
            self.active.discard(ticket.token)
            logger.info(
                "Inference released: endpoint=%s request=%s certain=%s",
                ticket.key,
                ticket.token,
                certain,
            )
            if certain and current and current["token"] == ticket.token:
                self._write({key: row for key, row in records.items() if key != ticket.key})

    def status(self) -> list[dict]:
        with self.lock:
            return [
                {
                    "endpoint_id": key,
                    **row,
                    "status": "RUNNING" if row["token"] in self.active else "UNCERTAIN",
                }
                for key, row in self._load().items()
            ]

    def acknowledge_stopped(self, key: str, token: str) -> None:
        with self.lock:
            records = self._load()
            current = records.get(key)
            if current is None or current["token"] != token:
                raise InferenceQueueError("Reservation changed; refresh before retrying.")
            if token in self.active:
                raise InferenceQueueError("A live request cannot be cleared.")
            self._write({name: row for name, row in records.items() if name != key})
            logger.info(
                "Inference uncertainty acknowledged by administrator: endpoint=%s request=%s",
                key,
                token,
            )
