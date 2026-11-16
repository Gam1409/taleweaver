"""Bounded proposals for session-local places; no executable content or model IDs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.models.session_state import SessionState

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


class CompanionArrival(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    npc_id: str = Field(min_length=1, max_length=100)
    evidence: str = Field(min_length=4, max_length=600)


class ExistingPlaceMatch(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    scene_id: str = Field(min_length=1, max_length=100)
    score: float = Field(
        ge=0,
        le=1,
        description="Contextual identity match, not label similarity: purpose, setting, route and current action.",
    )


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
    existing_scene_id: str | None = Field(default=None, max_length=100)
    identity_resolution: Literal["existing", "new", "ambiguous"] = "ambiguous"
    scene_matches: list[ExistingPlaceMatch] = Field(default_factory=list, max_length=3)
    label: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=1800)
    companions: list[CompanionArrival] = Field(default_factory=list, max_length=12)


def registry(state: SessionState) -> dict:
    raw = (state.entity_states or {}).get(KEY)
    return raw if isinstance(raw, dict) else {}


def policy(state: SessionState) -> LocationPolicy:
    try:
        return LocationPolicy.model_validate(registry(state).get("policy") or {})
    except ValidationError:
        return LocationPolicy()


def save_registry(state: SessionState, data: dict) -> None:
    state.entity_states = {**(state.entity_states or {}), KEY: data}
