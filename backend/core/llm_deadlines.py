"""Operation deadlines follow the same configuration as the selected LLM role."""

from typing import Any

from backend.core.config import settings
from backend.core.llm_roles import resolve_llm_role


def role_timeout(user: Any, role: str) -> float:
    """Resolve without opening a client, so queue leases can cover the entire request."""
    config = resolve_llm_role(dict(getattr(user, "llm_settings", None) or {}), role)
    default = (
        settings.WORLDBUILDING_TIMEOUT if role == "generator" else settings.INTELLIGENCE_TIMEOUT
    )
    return float(config.timeout if config.timeout is not None else default)
