"""Optional endpoint overrides retain one shared OpenAI-compatible provider default."""

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from backend.core.llm_roles import LLM_ROLES

ROLE_DEFAULTS: dict[str, str] = {f"{role}_custom_openai_url": "" for role in LLM_ROLES}


class CustomOpenAIRoleSettings(BaseModel):
    small_custom_openai_url: str | None = Field(default="", max_length=2048)
    complex_custom_openai_url: str | None = Field(default="", max_length=2048)
    generator_custom_openai_url: str | None = Field(default="", max_length=2048)
    compression_custom_openai_url: str | None = Field(default="", max_length=2048)
    play_agent_custom_openai_url: str | None = Field(default="", max_length=2048)


def resolve_url(settings: dict[str, Any], role: str = "") -> str:
    override = settings.get(f"{role}_custom_openai_url") if role in LLM_ROLES else ""
    return (
        str(override or "").strip() or str(settings.get("custom_openai_url") or "").strip()
    ).rstrip("/")


def validate_urls(payload: CustomOpenAIRoleSettings, validate: Callable[[str], str]) -> None:
    for key in ROLE_DEFAULTS:
        value = str(getattr(payload, key) or "").strip()
        setattr(payload, key, validate(value) if value else "")
