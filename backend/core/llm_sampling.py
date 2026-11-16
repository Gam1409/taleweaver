"""Explicit sampling profiles, independent of provider/model role inheritance."""

from copy import deepcopy
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from backend.core.llm_roles import LLMRole


class SamplingProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    temperature: float | None = Field(default=None, ge=0, le=2, strict=True)
    top_p: float | None = Field(default=None, gt=0, le=1, strict=True)
    top_k: int | None = Field(default=None, ge=0, le=1000, strict=True)
    min_p: float | None = Field(default=None, ge=0, le=1, strict=True)
    repetition_penalty: float | None = Field(default=None, gt=0, le=2, strict=True)
    local_extensions: StrictBool = False

    @field_validator("temperature", "top_p", "top_k", "min_p", "repetition_penalty", mode="before")
    @classmethod
    def empty_number(cls, value: Any) -> Any:
        return None if isinstance(value, str) and not value.strip() else value


class SamplingOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: StrictBool = False
    profile: SamplingProfile = Field(default_factory=SamplingProfile)


class SamplingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    defaults: SamplingProfile = Field(default_factory=SamplingProfile)
    roles: dict[LLMRole, SamplingOverride] = Field(default_factory=dict, max_length=5)


def resolve(settings: dict[str, Any], role: str | None) -> SamplingProfile:
    sampling = SamplingSettings.model_validate(settings.get("sampling") or {})
    override = next((value for key, value in sampling.roles.items() if key == role), None)
    return override.profile if override and override.enabled else sampling.defaults


def apply(kwargs: dict[str, Any], profile: SamplingProfile, provider: str) -> None:
    """Unset values stay absent; local extensions never leak to cloud providers."""
    standard = profile.model_dump(include={"temperature", "top_p"}, exclude_none=True)
    kwargs.update(standard)
    local = profile.model_dump(include={"top_k", "min_p", "repetition_penalty"}, exclude_none=True)
    if provider == "ollama":
        if "repetition_penalty" in local:
            local["repeat_penalty"] = local.pop("repetition_penalty")
        kwargs.update(local)
    elif provider == "custom_openai" and profile.local_extensions and local:
        # OpenAI SDK's extra_body merges these into the request JSON. The wire
        # name repetition_penalty is accepted by KoboldCpp's compatible API.
        kwargs["extra_body"] = {**kwargs.get("extra_body", {}), **local}


def temporary(settings: dict, role: LLMRole, profile: SamplingProfile) -> dict:
    """A connection test uses the unsaved effective profile without persisting it."""
    result = deepcopy(settings)
    sampling = SamplingSettings.model_validate(result.get("sampling") or {})
    sampling.roles[role] = SamplingOverride(enabled=True, profile=profile)
    result["sampling"] = sampling.model_dump()
    return result
