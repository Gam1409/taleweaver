"""Safe, actionable responses for authoring model failures."""

from fastapi import HTTPException
from litellm.exceptions import AuthenticationError, PermissionDeniedError, RateLimitError, Timeout

from backend.core.inference.player_errors import player_message


def generation_error(error: Exception, *, subject: str = "item") -> HTTPException:
    admission_message = player_message(error)
    if admission_message:
        return HTTPException(503, admission_message)
    if isinstance(error, (AuthenticationError, PermissionDeniedError)):
        return HTTPException(
            503,
            "The AI provider rejected access. Check its API key and model permissions in Settings.",
        )
    if isinstance(error, RateLimitError):
        return HTTPException(
            429, "The AI provider's request limit was reached. Please try again later."
        )
    if isinstance(error, (Timeout, TimeoutError)):
        return HTTPException(504, "The AI provider timed out. Check its status before retrying.")
    return HTTPException(502, f"Could not generate a valid {subject} draft. Please try again.")
