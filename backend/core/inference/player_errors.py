"""Translate admission failures without exposing endpoint or reservation details."""

import logging

from backend.core.inference.registry import InferenceQueueError, InferenceUncertainError

logger = logging.getLogger(__name__)


def player_message(error: Exception) -> str | None:
    if isinstance(error, InferenceUncertainError):
        logger.warning(
            "Inference admission blocked: previous request completion is unconfirmed; administrator recovery is required"
        )
        return "The Game Master is temporarily unavailable. Please contact the administrator before trying again."
    if isinstance(error, InferenceQueueError):
        logger.warning("Inference admission deferred: queue unavailable")
        return "The Game Master is busy right now. Please try again shortly."
    return None


def retryable(error: Exception) -> bool:
    return not isinstance(error, InferenceUncertainError)
