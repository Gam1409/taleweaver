"""Content-free request chains shared by console and optional system debug logs."""

import logging

import httpx

from backend.core import system_diagnostics
from backend.core.diagnostic_fields import safe_error

logger = logging.getLogger(__name__)


def emit(
    stage: str,
    *,
    reservation_id: str | None = None,
    error: BaseException | None = None,
    **fields: object,
) -> None:
    service = system_diagnostics.service
    context = service.current_context()
    safe = {**context, **fields}
    if reservation_id is not None:
        safe["reservation_id"] = reservation_id
    service.emit("inference." + stage, **safe, error=error)
    logger.info(
        "Inference %s: request=%s call=%s reservation=%s role=%s purpose=%s phase=%s timeout=%s elapsed_ms=%s reason=%s error=%s",
        stage,
        safe.get("request_id", "-"),
        safe.get("call_id", "-"),
        reservation_id or "-",
        safe.get("role", "-"),
        safe.get("purpose", "-"),
        safe.get("phase", "-"),
        safe.get("timeout_seconds", "-"),
        safe.get("duration_ms", "-"),
        safe.get("inference_reason") or "-",
        safe_error(error) if error else "-",
    )


async def sent(request: httpx.Request) -> None:
    if request.method == "POST":
        emit("sent")
