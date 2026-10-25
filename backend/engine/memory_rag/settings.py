"""Independent, opt-in embedding configuration; credentials stay in the user vault."""

import hashlib
import json
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MemoryRagSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    provider: Literal["openai", "ollama"] = "openai"
    base_url: str = ""
    model: str = Field(default="", max_length=256)
    timeout_seconds: float = Field(default=10, ge=1, le=60, allow_inf_nan=False)

    @field_validator("base_url")
    @classmethod
    def normalize_url(cls, value: str) -> str:
        return normalize_base_url(value)

    @field_validator("model")
    @classmethod
    def normalize_model(cls, value: str) -> str:
        return value.strip()


def normalize_base_url(value: str) -> str:
    """Canonicalize without DNS or network access, including for disabled settings."""
    value = value.strip().rstrip("/")
    if not value:
        return ""
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Embedding URL must be an HTTP or HTTPS URL with a hostname.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Embedding URL must not contain credentials, a query, or a fragment.")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("Embedding URL port is invalid.")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, "", ""))


def read_settings(user: Any) -> MemoryRagSettings:
    raw = (getattr(user, "llm_settings", None) or {}).get("memory_rag") or {}
    return MemoryRagSettings.model_validate(raw)


def embedding_signature(settings: MemoryRagSettings, dimension: int) -> str:
    """Keep vector spaces separate without incorporating credentials."""
    if dimension < 1:
        raise ValueError("Embedding dimension must be positive.")
    payload = [settings.provider, settings.base_url, settings.model, dimension]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()
