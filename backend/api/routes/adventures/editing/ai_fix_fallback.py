"""Do not bypass an unconfirmed local request through a different fallback endpoint."""

from typing import Any

from backend.core.inference import admission
from backend.core.inference.registry import (
    InferenceQueueError,
    InferenceUncertainError,
    endpoint_key,
)


def reject_uncertain_fallback(router: Any, error: Exception) -> None:
    if isinstance(error, InferenceUncertainError):
        raise error
    if not admission.enabled() or getattr(router, "provider", "") not in {
        "ollama",
        "custom_openai",
    }:
        return
    key = endpoint_key(router.api_base)
    records = admission.registry().status()
    if isinstance(error, TimeoutError) and any(
        row["endpoint_id"].split(":", 1)[0] == key and row["status"] == "RUNNING" for row in records
    ):
        raise InferenceQueueError(
            "The previous submitted request is still being monitored. Wait for it to finish before retrying."
        ) from error
    if any(
        row["endpoint_id"].split(":", 1)[0] == key and row["status"] == "UNCERTAIN"
        for row in records
    ):
        raise InferenceUncertainError(
            "Completion of the previous request is unconfirmed. Check the inference queue before retrying."
        ) from error
