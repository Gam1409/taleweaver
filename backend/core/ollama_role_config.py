"""Optional Ollama overrides for all five LLM roles, with legacy fallbacks."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from backend.core.llm_roles import LLM_ROLES, LLMRole

OLLAMA_ROLE_DEFAULTS: dict[str, Any] = {
    f"{role}_ollama_{option}": default
    for role in LLM_ROLES
    for option, default in (("url", ""), ("timeout", None), ("num_ctx", None))
}


def empty_number(value: Any) -> Any:
    """HTML number inputs send an empty string when cleared, not zero."""
    return None if isinstance(value, str) and not value.strip() else value


class OllamaRoleSettings(BaseModel):
    """Persisted role overrides; omitted numbers inherit the runtime defaults."""

    ollama_api_mode: Literal["generate", "chat"] = "generate"

    small_ollama_url: str | None = ""
    small_ollama_timeout: int | None = Field(default=None, ge=30, le=600)
    small_ollama_num_ctx: int | None = Field(default=None, ge=512, le=1048576)
    complex_ollama_url: str | None = ""
    complex_ollama_timeout: int | None = Field(default=None, ge=30, le=600)
    complex_ollama_num_ctx: int | None = Field(default=None, ge=512, le=1048576)

    generator_ollama_url: str | None = ""
    generator_ollama_timeout: int | None = Field(default=None, ge=30, le=600)
    generator_ollama_num_ctx: int | None = Field(default=None, ge=512, le=1048576)
    compression_ollama_url: str | None = ""
    compression_ollama_timeout: int | None = Field(default=None, ge=30, le=600)
    compression_ollama_num_ctx: int | None = Field(default=None, ge=512, le=1048576)
    play_agent_ollama_url: str | None = ""
    play_agent_ollama_timeout: int | None = Field(default=None, ge=30, le=600)
    play_agent_ollama_num_ctx: int | None = Field(default=None, ge=512, le=1048576)

    @field_validator(
        "small_ollama_timeout",
        "small_ollama_num_ctx",
        "complex_ollama_timeout",
        "complex_ollama_num_ctx",
        "generator_ollama_timeout",
        "generator_ollama_num_ctx",
        "compression_ollama_timeout",
        "compression_ollama_num_ctx",
        "play_agent_ollama_timeout",
        "play_agent_ollama_num_ctx",
        mode="before",
    )
    @classmethod
    def normalize_numbers(cls, value: Any) -> Any:
        return empty_number(value)


class OllamaConnectionSettings(BaseModel):
    """Temporary overrides used by the existing model test endpoint."""

    role: LLMRole = "small"
    ollama_api_mode: Literal["generate", "chat"] | None = None
    ollama_timeout: int | None = Field(default=None, ge=30, le=600)
    ollama_num_ctx: int | None = Field(default=None, ge=512, le=1048576)

    @field_validator("ollama_timeout", "ollama_num_ctx", mode="before")
    @classmethod
    def normalize_numbers(cls, value: Any) -> Any:
        return empty_number(value)


def validate_role_urls(payload: OllamaRoleSettings, validate: Callable[[str], str]) -> None:
    """Validate new URLs without changing validation of the legacy global URL."""
    for role in LLM_ROLES:
        key = f"{role}_ollama_url"
        value = (getattr(payload, key) or "").strip()
        setattr(payload, key, validate(value).rstrip("/") if value else "")


@dataclass(frozen=True)
class OllamaRuntimeSettings:
    url: str
    timeout: int | None = None
    num_ctx: int | None = None


def resolve_ollama_role_settings(settings: dict[str, Any], category: str) -> OllamaRuntimeSettings:
    """Legacy constructors apply overrides only for an explicitly configured Ollama role."""
    global_url = ((settings.get("ollama_url") or "").strip() or "http://localhost:11434").rstrip(
        "/"
    )
    if category not in LLM_ROLES or settings.get(f"{category}_model_provider") != "ollama":
        return OllamaRuntimeSettings(global_url)
    url = (settings.get(f"{category}_ollama_url") or "").strip().rstrip("/")
    return OllamaRuntimeSettings(
        url or global_url,
        settings.get(f"{category}_ollama_timeout"),
        settings.get(f"{category}_ollama_num_ctx"),
    )


def temporary_ollama_settings(
    original: dict[str, Any],
    payload: OllamaConnectionSettings,
    url: str | None,
    provided_fields: set[str],
    validate: Callable[[str], str],
) -> dict[str, Any]:
    """Overlay only supplied test fields; never persist them to the settings owner."""
    result = dict(original)
    role = payload.role
    result[f"{role}_model_provider"] = "ollama"
    if payload.ollama_api_mode is not None:
        result["ollama_api_mode"] = payload.ollama_api_mode
    if "ollama_url" in provided_fields:
        candidate = (url or "").strip()
        result[f"{role}_ollama_url"] = validate(candidate).rstrip("/") if candidate else ""
    for option in ("timeout", "num_ctx"):
        key = f"ollama_{option}"
        if key in provided_fields:
            result[f"{role}_{key}"] = getattr(payload, key)
    return result


def preserve_explicit_ollama_models(normalized: dict[str, Any], original: dict[str, Any]) -> None:
    """Do not silently replace an explicitly selected Ollama role during normalization."""
    for role in LLM_ROLES:
        if original.get(f"{role}_model_provider") == "ollama":
            normalized[f"{role}_model_provider"] = "ollama"
            normalized[f"{role}_model"] = original.get(f"{role}_model") or ""
