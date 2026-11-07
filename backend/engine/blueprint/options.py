"""Public preflight options, bounded independently from arbitrary generator form data."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BlueprintOptions(BaseModel):
    model_config = ConfigDict(extra="ignore")

    rule_enforcement_mode: Literal["rpg", "story", "chat", "vn"] | None = "rpg"
    scripts_generation_enabled: bool | None = None
    container_generation_enabled: bool | None = None
    text_log_generation_enabled: bool | None = None
    quest_generation_enabled: bool | None = None
    award_generation_enabled: bool | None = None
    max_scenes: int | None = Field(default=None, ge=0, le=1000)
    max_items: int | None = Field(default=None, ge=0, le=1000)
    max_sequences: int | None = Field(default=None, ge=0, le=1000)
