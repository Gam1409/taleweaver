"""Serial service lifecycle operations; no UI callback waits for process shutdown."""

import http.client
import logging
import os
import queue
import secrets
import signal
import socket
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

from desktop import health
from desktop.paths import child_environment, prepare
from scripts.desktop_processes import start_service

logger = logging.getLogger(__name__)


class Controller:
    def __init__(
        self,
        root: Path,
        config: Path,
        port: int,
        changed: Callable[[str], None],
        exited: Callable[[], None] = lambda: None,
        *,
        startup_timeout: float = 120,
    ) -> None:
        self.root, self.config, self.port = root, config, port
        self.changed, self.exited = changed, exited
        self.startup_timeout = startup_timeout
        self.state = "stopped"
        self.process: subprocess.Popen | None = None
        self.token = secrets.token_urlsafe(24)
        self.deadline = 0.0
        self.actions: queue.Queue[str] = queue.Queue()
        self.worker = threading.Thread(target=self._run, name="desktop-supervisor", daemon=True)

    def launch(self) -> None:
        self.worker.start()
        self.request("start")

    def request(self, action: str) -> None:
        if action not in {"start", "stop", "restart", "exit"}:
            raise ValueError("Unknown desktop action.")
        self.actions.put(action)

    def _state(self, value: str) -> None:
        if value != self.state:
            self.state = value
            logger.info("Service state: %s", value)
            try:
                self.changed(value)
            except Exception:
                logger.exception("Tray update failed; service supervision remains active.")

    def _start(self) -> None:
        if self.process is not None and self.process.poll() is None:
            return
        self._state("starting")
        self.config, self.port = prepare(self.root)
        self.token = secrets.token_urlsafe(24)
        # Refuse an occupied port. Stop/Exit must never act on another server.
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", self.port))
        self.process = start_service(
            self.root, child_environment(self.root, self.config, self.token)
        )
        self.deadline = time.monotonic() + self.startup_timeout
        threading.Thread(target=self._drain, args=(self.process,), daemon=True).start()

    @staticmethod
    def _drain(process: subprocess.Popen) -> None:
        if process.stdout is not None:
            with process.stdout:
                for line in process.stdout:
                    logger.info("server: %s", line.rstrip())

    def _stop(self) -> None:
        process = self.process
        if process is None or process.poll() is not None:
            self._state("stopped")
            return
        self._state("stopping")
        try:
            health.request(self.port, "/_desktop/stop", token=self.token, method="POST")
        except (OSError, ValueError, http.client.HTTPException):
            logger.info("Graceful shutdown endpoint unavailable; stopping the owned process.")
            self._signal(process, force=False)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._signal(process, force=True)
            process.wait(timeout=5)
        self.process = None
        self._state("stopped")

    @staticmethod
    def _signal(process: subprocess.Popen, *, force: bool) -> None:
        try:
            if os.name == "nt":
                process.kill() if force else process.terminate()
                return
            os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
        except ProcessLookupError:
            logger.debug("Owned process already stopped.")

    def _check(self) -> None:
        if self.process is None:
            return
        if self.process.poll() is not None:
            self._state("error")
            return
        if health.ready(self.port, self.token):
            self._state("running")
            return
        if self.state != "starting" or time.monotonic() >= self.deadline:
            self._state("error")

    def _run(self) -> None:
        while True:
            try:
                action = self.actions.get(timeout=2)
            except queue.Empty:
                self._check()
                continue
            try:
                if action in {"stop", "restart", "exit"}:
                    self._stop()
                if action in {"start", "restart"}:
                    self._start()
            except Exception:
                logger.exception("Desktop service operation failed.")
                self._state("error")
            if action == "exit":
                self.exited()
                return
