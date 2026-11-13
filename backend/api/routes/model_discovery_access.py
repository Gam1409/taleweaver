"""Bind shared model-discovery credentials to administrator-selected endpoints."""

from fastapi import HTTPException

from backend.models.user import User
from backend.utils.path_security import validate_provider_url


def checked_discovery_base(user: User, override: str | None, configured: str) -> str:
    """Readers may use the configured endpoint; only administrators may replace it."""
    candidate = (override or configured).strip()
    if user.role != "admin" and candidate.rstrip("/") != configured.strip().rstrip("/"):
        raise HTTPException(
            status_code=403,
            detail="Only administrators can override model discovery endpoints.",
        )
    try:
        return validate_provider_url(candidate)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
