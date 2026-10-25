"""Bounded private social memory and the deliberately narrow Small-role contract."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_ACTIVE = 3
MAX_CAST = 64
MAX_MEMORY = 12
MAX_PROCESSED = 128
MAX_FINGERPRINTS = 64
STATE_KEY = "__vn_state__"
EventKind = Literal[
    "none",
    "compliment",
    "support",
    "cooperation",
    "boundary_respected",
    "boundary_violated",
    "betrayal",
    "conflict",
]
Emotion = Literal["neutral", "curious", "pleased", "concerned", "hurt", "angry", "guarded"]
Intention = Literal[
    "listen", "clarify", "reassure", "set_boundary", "reflect", "cooperate", "withdraw"
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SocialProposal(StrictModel):
    npc_id: str = Field(min_length=1, max_length=50)
    source: Literal["player_action", "scene_context"]
    evidence: str = Field(min_length=4, max_length=700)
    basis: Literal["performed_interaction", "claim", "hypothetical", "uncertain"]
    event: EventKind = "none"
    emotion: Emotion = "neutral"
    intention: Intention = "listen"


class InteractionPlan(StrictModel):
    reactions: list[SocialProposal] = Field(default_factory=list, max_length=MAX_ACTIVE)


class Relationship(StrictModel):
    trust: int = Field(default=0, ge=-100, le=100)
    affinity: int = Field(default=0, ge=-100, le=100)
    respect: int = Field(default=0, ge=-100, le=100)
    tension: int = Field(default=0, ge=0, le=100)


class SocialMemory(StrictModel):
    event_id: str = Field(max_length=64)
    source_message_id: str = Field(max_length=64)
    kind: EventKind
    evidence: str = Field(max_length=700)


class CharacterState(StrictModel):
    core: str = Field(default="", max_length=1000)
    goals: list[Annotated[str, Field(max_length=1000)]] = Field(default_factory=list, max_length=2)
    relationship: Relationship = Field(default_factory=Relationship)
    emotion: Emotion = "neutral"
    emotion_cause: str = Field(default="", max_length=700)
    next_intention: Intention = "listen"
    pinned: bool = False
    meaningful_events: int = Field(default=0, ge=0, le=1000)
    last_positive_turn: int = Field(default=-10, ge=-10)
    last_source_message_id: str = Field(default="", max_length=64)
    fingerprints: list[str] = Field(default_factory=list, max_length=MAX_FINGERPRINTS)
    memories: list[SocialMemory] = Field(default_factory=list, max_length=MAX_MEMORY)


class SocialState(StrictModel):
    version: Literal[1] = 1
    turn: int = Field(default=0, ge=0)
    characters: dict[str, CharacterState] = Field(default_factory=dict, max_length=MAX_CAST)
    processed_message_ids: list[str] = Field(default_factory=list, max_length=MAX_PROCESSED)
