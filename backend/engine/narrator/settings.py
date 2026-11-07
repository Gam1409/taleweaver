"""Author defaults and frozen session preferences in existing manifest JSON."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

MANIFEST_KEY = "narrator_settings"
SETTINGS_KEY = "__narrator_settings__"

Verbosity = Literal["default", "terse", "dialogue", "balanced", "rich", "epic"]


class NarratorVoice(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=300)
    instruction: str = Field(min_length=1, max_length=1500)
    sample: str = Field(default="", max_length=500)


class NarratorSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voice: NarratorVoice | None = None
    verbosity: Verbosity = "default"


def _read(raw: Any) -> NarratorSettings:
    try:
        return NarratorSettings.model_validate(raw or {})
    except ValidationError:
        return NarratorSettings()


def manifest_settings(manifest: Any) -> NarratorSettings:
    block = manifest if isinstance(manifest, dict) else {}
    # Standard ADV exports keep author presentation alongside other extensions.
    return _read(block.get(MANIFEST_KEY))


def read_settings(state: Any) -> NarratorSettings:
    """A session override wins over its frozen manifest; never read a live template."""
    states = getattr(state, "entity_states", None)
    if not isinstance(states, dict):
        return NarratorSettings()
    if SETTINGS_KEY in states:
        return _read(states[SETTINGS_KEY])
    snapshot = states.get("__manifest_snapshot__")
    manifest = snapshot.get("original_manifest") if isinstance(snapshot, dict) else None
    return manifest_settings(manifest)


def preserve_settings(manifest: dict, adventure: Any) -> dict:
    """A generated world cannot change an author's presentation choices."""
    previous = getattr(adventure, "original_manifest", None)
    return {**manifest, MANIFEST_KEY: manifest_settings(previous).model_dump()}
