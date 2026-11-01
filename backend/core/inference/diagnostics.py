"""Actionable settings diagnostics for requests blocked before provider submission."""

from backend.core.inference.registry import InferenceQueueError, InferenceUncertainError


def admission_diagnostic(error: Exception) -> str | None:
    if isinstance(error, InferenceUncertainError):
        return (
            "No generation request was sent. TaleWeaver's inference queue is blocked because "
            "completion of a previous request is unconfirmed. Model discovery can still work. "
            "Check that generation has stopped on the model server, or restart that server. "
            "Then open Administration > Intelligence (LLM) > Inference queue, click Refresh queue, "
            "confirm the UNCERTAIN request has stopped and click Clear stopped request. "
            "Ask an administrator if you cannot access this panel, then repeat the model test."
        )
    if isinstance(error, InferenceQueueError):
        return (
            "No generation request was sent. TaleWeaver could not admit this request to the "
            "inference queue. Open Administration > Intelligence (LLM) > Inference queue "
            "and click Refresh queue to check outstanding requests. Wait for active requests "
            "to finish before testing again; ask an administrator if the queue remains blocked."
        )
    return None
