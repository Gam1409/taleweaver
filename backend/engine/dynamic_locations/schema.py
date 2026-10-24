"""Bounded proposals for session-local places; no executable content or model IDs."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

KEY = "__dynamic_locations__"
MAX_PLACES = 48
MAX_CHILDREN = 8
MAX_DEPTH = 3


class LocationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    scale: Literal["auto", "regional", "building"] = "auto"
    generate_images: bool = True


class PlaceProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=100)
    action_quote: str = Field(min_length=1, max_length=600)


class PlaceDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    arrival_now: bool
    player_moves: bool
    local_to_current_scene: bool
    access_allowed: bool
    contradicts_world: bool
    world_scale: Literal["regional", "building"]
    granularity: Literal["site", "room", "detail"]
    purpose: Literal["ordinary", "overnight", "investigation", "persistent"]
    action_quote: str = Field(default="", max_length=600)
    purpose_quote: str = Field(default="", max_length=600)
    existing_scene_id: str | None = Field(default=None, max_length=50)
    label: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=1800)


def registry(state) -> dict:
    raw = (state.entity_states or {}).get(KEY)
    return raw if isinstance(raw, dict) else {}


def policy(state) -> LocationPolicy:
    try:
        return LocationPolicy.model_validate(registry(state).get("policy") or {})
    except ValidationError:
        return LocationPolicy()


def save_registry(state, data: dict) -> None:
    state.entity_states = {**(state.entity_states or {}), KEY: data}
