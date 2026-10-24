"""Serializable prompt policies; workflow parameters never come from the language model."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ImagePromptRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template_id: str = Field(default="custom", max_length=80)
    format: Literal["description", "tags", "hybrid"] = "description"
    language: str = Field(default="English", min_length=1, max_length=80)
    max_words: int = Field(default=100, ge=10, le=300)
    adapt_with_llm: bool = True
    prefix: str = Field(default="", max_length=2000)
    suffix: str = Field(default="", max_length=2000)
    negative_prompt: str = Field(default="", max_length=4000)
    instructions: str = Field(default="", max_length=4000)
