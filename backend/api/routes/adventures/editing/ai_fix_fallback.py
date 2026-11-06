"""Do not bypass an unconfirmed local request through a different fallback endpoint."""

from typing import Any

from backend.core.inference import admission
from backend.core.inference.registry import InferenceUncertainError, endpoint_key


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
    if any(
        row["endpoint_id"].split(":", 1)[0] == key and row["status"] == "UNCERTAIN"
        for row in records
    ):
        raise InferenceUncertainError(
            "Completion of the previous request is unconfirmed. Check the inference queue before retrying."
        ) from error
