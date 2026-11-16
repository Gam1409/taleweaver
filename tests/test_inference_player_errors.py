"""Expected queue fences produce private, non-retrying player feedback."""

from backend.api.routes.adventures.gameplay_logic import _friendly_llm_error_message
from backend.core.inference.player_errors import retryable
from backend.core.inference.registry import InferenceQueueError, InferenceUncertainError


def test_uncertain_request_is_recognized_without_leaking_details(caplog):
    error = InferenceUncertainError("private endpoint and reservation token")
    message = _friendly_llm_error_message(error)
    assert message and "administrator" in message
    assert not retryable(error)
    assert "private endpoint" not in message + caplog.text
    assert "unconfirmed" in caplog.text


def test_queue_wait_can_be_retried_without_exposing_internal_error():
    error = InferenceQueueError("secret URL")
    assert "busy" in _friendly_llm_error_message(error)
    assert retryable(error)
    assert "secret" not in _friendly_llm_error_message(error)
