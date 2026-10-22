"""Adapt existing constructor fakes to the public role-based LLM factory."""

from collections.abc import Callable
from typing import Any

from backend.core.llm_roles import resolve_llm_role


class RoleLLMFactory:
    """Keep real role resolution while replacing the network-facing router."""

    def __init__(self, factory: Callable[..., Any]) -> None:
        self.factory = factory

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.factory(*args, **kwargs)

    def for_role(self, user: Any, role: str, **overrides: Any) -> Any:
        settings = dict(user.llm_settings or {})
        for key in ("provider", "model"):
            if overrides.get(key):
                field = f"{role}_model_provider" if key == "provider" else f"{role}_model"
                settings[field] = overrides[key]
        config = resolve_llm_role(settings, role)
        router = self.factory(user, provider=config.provider, model_category=role)
        router.model = config.model
        router.provider = config.provider
        return router
