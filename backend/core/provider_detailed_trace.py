"""Explicit image/embedding payloads correlated with the existing provider lifecycle."""

from typing import Any

from backend.core.diagnostic_fields import safe_error
from backend.core.system_diagnostics import service

FIELDS = {
    "texts",
    "prompt",
    "negative_prompt",
    "model",
    "provider",
    "width",
    "height",
    "seed",
    "timeout",
    "purpose",
    "settings",
    "provider_options",
    "image_task",
    "reference_image",
}


def start(kind: str, context: dict, arguments: dict) -> int | None:
    token = service.capture_token()
    if token is not None:
        service.detail(
            f"detail.{kind}.request",
            token=token,
            **context,
            request={key: part for key, part in arguments.items() if key in FIELDS},
        )
    return token


def finish(
    kind: str,
    context: dict,
    token: int | None,
    result: Any = None,
    error: BaseException | None = None,
) -> None:
    if token is not None:
        service.detail(
            f"detail.{kind}.{'failed' if error else 'response'}",
            token=token,
            **context,
            result=result,
            error=safe_error(error) if error else None,
        )
