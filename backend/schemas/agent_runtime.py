"""Portable authoring contract v1; no engine, network or persistence dependencies."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")]
Feature = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_.-]*$")]


class Portable(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True, allow_inf_nan=False)


class Versioned(Portable):
    schema_version: Annotated[int, Field(ge=1, le=1)]

    @model_validator(mode="after")
    def no_session_payload(self) -> "Versioned":
        reserved = {
            "session_state",
            "runtime_state",
            "memories",
            "psychological_state",
            "relationships",
        }
        if reserved & (self.model_extra or {}).keys():
            raise ValueError("Mutable session fields cannot be authored in this namespace.")
        return self


class Autonomy(Portable):
    enabled: bool = False
    max_active_npcs: int = Field(default=3, ge=1, le=20)


class Psychology(Portable):
    enabled: bool = False
    model: Literal["authored-categorical-v1"] = "authored-categorical-v1"
    observer_memory_limit: int = Field(default=12, ge=0, le=24)


class CorpusRef(Portable):
    id: Identifier
    source: Literal["installed", "remote"] = "installed"
    library_id: Identifier | None = None
    revision: Annotated[str, Field(min_length=1, max_length=100)]
    sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    required: bool = False

    @model_validator(mode="after")
    def remote_library(self) -> "CorpusRef":
        if (self.source == "remote") != (self.library_id is not None):
            raise ValueError("Only a remote corpus requires a locally configured library ID.")
        return self


class Rag(Portable):
    enabled: bool = False
    top_k: int = Field(default=8, ge=1, le=32)
    audience_policy: Literal["observer-scoped-v1"] = "observer-scoped-v1"
    corpora: list[CorpusRef] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def unique_corpora(self) -> "Rag":
        if len({item.id for item in self.corpora}) != len(self.corpora):
            raise ValueError("Corpus IDs must be unique.")
        return self


class LivingWorld(Portable):
    enabled: bool = False
    absence_mode: Literal["pause", "catch_up"] = "pause"
    max_catchup_minutes: int = Field(default=360, ge=0, le=4320)
    max_events: int = Field(default=16, ge=0, le=128)


class AgentRuntime(Versioned):
    required_features: list[Feature] = Field(default_factory=list, max_length=32)
    optional_features: list[Feature] = Field(default_factory=list, max_length=32)
    fallback: Literal["core", "block"] = "core"
    autonomy: Autonomy = Field(default_factory=Autonomy)
    psychology: Psychology = Field(default_factory=Psychology)
    rag: Rag = Field(default_factory=Rag)
    living_world: LivingWorld = Field(default_factory=LivingWorld)

    @model_validator(mode="after")
    def declared_features(self) -> "AgentRuntime":
        declarations = self.required_features + self.optional_features
        if len(set(declarations)) != len(declarations):
            raise ValueError("Feature declarations must be unique and disjoint.")
        parents = {
            "library.remote.v1": "rag.observer.v1",
            "living_world.catch_up.v1": "living_world.v1",
        }
        if any(
            child in self.required_features and parent not in self.required_features
            for child, parent in parents.items()
        ):
            raise ValueError("Required child capabilities require their parent capability.")
        if not self.requested_features() <= set(declarations):
            raise ValueError("Every enabled capability must be declared as required or optional.")
        if any(item.required for item in self.rag.corpora) and (
            not self.rag.enabled or "rag.observer.v1" not in self.required_features
        ):
            raise ValueError("Required corpora require required RAG support.")
        if any(item.required and item.source == "remote" for item in self.rag.corpora) and (
            "library.remote.v1" not in self.required_features
        ):
            raise ValueError("Required remote corpora require the remote library capability.")
        return self

    def requested_features(self) -> set[str]:
        switches = {
            "npc.autonomy.v1": self.autonomy.enabled,
            "psychology.authored.v1": self.psychology.enabled,
            "rag.observer.v1": self.rag.enabled,
            "living_world.v1": self.living_world.enabled,
            "living_world.catch_up.v1": self.living_world.enabled
            and self.living_world.absence_mode == "catch_up",
            "library.remote.v1": self.rag.enabled
            and any(item.source == "remote" for item in self.rag.corpora),
        }
        return {name for name, enabled in switches.items() if enabled}


class RelationshipSeed(Portable):
    target_id: Identifier
    description: Annotated[str, Field(min_length=1, max_length=600)]


class InitialState(Portable):
    situation: Annotated[str, Field(max_length=1000)] = ""
    relationships: list[RelationshipSeed] = Field(default_factory=list, max_length=32)
    knowledge_entry_ids: list[Identifier] = Field(default_factory=list, max_length=64)


class NpcAgentRuntime(Versioned):
    autonomy: Literal["off", "reactive", "proactive"] = "off"
    initial_state: InitialState = Field(default_factory=InitialState)
    # The canonical NPC image_url is packed by existing archive code.
    visual_reference: Literal["image_url"] = "image_url"
