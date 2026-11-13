"""Presentation data never changes personality, relationships, or game rules."""

import hashlib
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    ValidationError,
)

EMOTIONS = (
    "calm",
    "joy",
    "affection",
    "love",
    "sexual_arousal",
    "ecstasy",
    "anger",
    "fear",
    "sadness",
    "embarrassment",
    "shame",
    "surprise",
    "interest",
    "trust",
    "hope",
    "anxiety",
    "disgust",
    "confusion",
    "determination",
    "tiredness",
    "boredom",
    "unknown",
)

MAX_EMOTION = 80
Emotion = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=MAX_EMOTION)
]
ColorChannel = Annotated[StrictInt, Field(ge=0, le=255)]
ColorRGB = Annotated[list[ColorChannel], Field(strict=True, min_length=3, max_length=3)]
MAX_THOUGHT = 160
MAX_NPCS = 20


class PortraitPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    emotion_palette: StrictBool = False
    character_thoughts: StrictBool = False
    brightness: StrictInt = Field(default=40, ge=0, le=100)

    @property
    def enabled(self) -> bool:
        return self.emotion_palette or self.character_thoughts


class PreferencesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    settings: PortraitPreferences
    expected: PortraitPreferences


class Cue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    emotion: Emotion | None = None
    intensity: StrictInt | None = Field(default=None, ge=0, le=100)
    color_rgb: ColorRGB | None = None
    thought: str | None = Field(default=None, max_length=MAX_THOUGHT)


class StoredCues(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    npcs: dict[Annotated[str, Field(min_length=1, max_length=128)], Cue] = Field(
        max_length=MAX_NPCS
    )


def source_hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode()).hexdigest()


def public_cues(value: Any, content: str) -> dict | None:
    """A changed or legacy response cannot inherit a different reply's emotions."""
    if not isinstance(value, dict) or value.get("source_hash") != source_hash(content):
        return None
    if value.get("version") != 1 or not isinstance(value.get("npcs"), dict):
        return None
    try:
        return StoredCues.model_validate(value).model_dump(exclude_none=True)
    except ValidationError:
        return None
