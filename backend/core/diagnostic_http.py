"""Observe ASGI transport metadata without reading request or response content."""

import asyncio
import time
from uuid import uuid4

from fastapi import Request

from backend.core.system_diagnostics import service


class DiagnosticMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = time.perf_counter()
        status_code = 0
        byte_count = 0
        disconnected = False
        failed = False

        async def observed_receive():
            nonlocal disconnected
            message = await receive()
            if message["type"] == "http.disconnect":
                disconnected = True
            return message

        async def observed_send(message):
            nonlocal status_code, byte_count
            if message["type"] == "http.response.start":
                status_code = message["status"]
            elif message["type"] == "http.response.body":
                byte_count += len(message.get("body", b""))
            await send(message)

        with service.context(request_id=uuid4().hex):
            service.http_event("http.started", scope, method=scope["method"])
            try:
                await self.app(scope, observed_receive, observed_send)
            except asyncio.CancelledError as error:
                failed = True
                service.http_event("http.cancelled", scope, error=error)
                raise
            except Exception as error:
                failed = True
                service.http_event("http.failed", scope, error=error)
                raise
            finally:
                service.http_event(
                    "http.disconnected" if disconnected else "http.completed",
                    scope,
                    method=scope["method"],
                    status_code=status_code,
                    success=not failed and not disconnected and 200 <= status_code < 400,
                    bytes_sent=byte_count,
                    duration_ms=(time.perf_counter() - started) * 1000,
                )


async def session_diagnostic_context(request: Request):
    """Bind session identity after routing; spawned jobs inherit only safe IDs."""
    with service.context(session_id=request.path_params.get("game_id")):
        yield
