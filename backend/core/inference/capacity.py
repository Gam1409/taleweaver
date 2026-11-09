"""Shared-origin pools; an exclusive request cannot overlap an opted-in role."""

from typing import Any

from backend.core.inference.registry import endpoint_key

PROVIDER_URLS = {
    "openai": "https://api.openai.com",
    "anthropic": "https://api.anthropic.com",
    "google": "https://generativelanguage.googleapis.com",
    "gemini": "https://generativelanguage.googleapis.com",
    "deepseek": "https://api.deepseek.com",
    "openrouter": "https://openrouter.ai",
}


def target(router: Any, kwargs: dict | None = None) -> str | None:
    """Use the effective wire endpoint, including provider routing overrides."""
    options = kwargs or {}
    configured = getattr(router, f"{router.provider}_api_base", None)
    url = (
        options.get("api_base")
        or router.api_base
        or configured
        or PROVIDER_URLS.get(router.provider)
    )
    return endpoint_key(url) if url else None


def limit(router: Any) -> int | None:
    policy = getattr(router, "parallel_policy", None)
    return policy.capacity if policy is not None else None
