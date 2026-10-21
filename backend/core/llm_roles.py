"""Resolve LLM providers and models together for the five application roles."""

from dataclasses import dataclass
from typing import Any, Literal

LLMRole = Literal["small", "complex", "generator", "compression", "play_agent"]
LLM_ROLES: tuple[LLMRole, ...] = ("small", "complex", "generator", "compression", "play_agent")
ROLE_DONORS: dict[str, tuple[str, ...]] = {
    "small": ("small", "complex"),
    "complex": ("complex", "small"),
    "generator": ("generator", "complex", "small"),
    "compression": ("compression", "small"),
    "play_agent": ("play_agent", "small", "complex"),
}


@dataclass(frozen=True)
class LLMRoleConfig:
    """A requested role and the matching provider/model selected for it."""

    role: str
    provider: str
    model: str
    source_role: str
    ollama_url: str
    timeout: int | None
    num_ctx: int | None


def resolve_llm_role(llm_settings: dict[str, Any], role: str) -> LLMRoleConfig:
    """Use a donor's model with its provider, preserving cloud default names.

    Ollama must have an explicitly configured model; a cloud default is never
    sent to a local server. Runtime overrides belong to the requested role,
    even when its provider/model pair is inherited from another role.
    """
    if role not in ROLE_DONORS:
        raise ValueError(f"Unknown LLM role '{role}'.")
    source = next(
        (donor for donor in ROLE_DONORS[role] if llm_settings.get(f"{donor}_model_provider")),
        role,
    )
    provider = llm_settings.get(f"{source}_model_provider")
    if not provider:
        provider = llm_settings.get("preferred_provider") if role != "compression" else None
    provider = str(provider or "openai").strip().lower()
    model = str(llm_settings.get(f"{source}_model") or "").strip()
    if provider == "ollama" and not model:
        raise ValueError(f"No model configured for role '{role}' (provider 'ollama').")
    default_model = "gpt-4o" if role in {"complex", "generator"} else "gpt-4o-mini"
    url = str(llm_settings.get(f"{role}_ollama_url") or "").strip()
    global_url = str(llm_settings.get("ollama_url") or "").strip()
    return LLMRoleConfig(
        role=role,
        provider=provider,
        model=model or default_model,
        source_role=source,
        ollama_url=(url or global_url or "http://localhost:11434").rstrip("/"),
        timeout=llm_settings.get(f"{role}_ollama_timeout") if provider == "ollama" else None,
        num_ctx=llm_settings.get(f"{role}_ollama_num_ctx") if provider == "ollama" else None,
    )
