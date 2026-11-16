"""Operation deadlines follow the same configuration as the selected LLM role."""

from typing import Any

from backend.core.config import settings
from backend.core.llm_roles import resolve_llm_role


def custom_openai_timeout(llm_settings: dict[str, Any]) -> int:
    """Shared provider limit for the HTTP client and surrounding operation timers."""
    return max(1, min(3600, int(llm_settings.get("custom_openai_timeout") or 300)))


def role_timeout(user: Any, role: str) -> float:
    """Resolve without opening a client, so queue leases can cover the entire request."""
    llm_settings = dict(getattr(user, "llm_settings", None) or {})
    config = resolve_llm_role(llm_settings, role)
    if config.provider == "custom_openai":
        return float(custom_openai_timeout(llm_settings))
    default = (
        settings.WORLDBUILDING_TIMEOUT if role == "generator" else settings.INTELLIGENCE_TIMEOUT
    )
    return float(config.timeout if config.timeout is not None else default)
