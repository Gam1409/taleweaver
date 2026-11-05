"""Source-bound subjective state, not a claim of calibrated human psychology."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=100)]
Text = Annotated[str, Field(min_length=1, max_length=2000)]
Sequence = Annotated[int, Field(ge=0, strict=True)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class Scope(Contract):
    world_id: Identifier
    branch_id: Identifier
    observer_id: Identifier


class AuthoredTrait(Contract):
    key: Identifier
    value: Annotated[str, Field(min_length=1, max_length=300)]


class Identity(Contract):
    source_revision: Identifier
    description: Text
    authored_goals: tuple[Text, ...] = Field(default=(), max_length=16)
    values: tuple[Text, ...] = Field(default=(), max_length=16)
    roles: tuple[Text, ...] = Field(default=(), max_length=16)
    # Preserve authored categorical data. There is no automatic Big Five mapping.
    traits: tuple[AuthoredTrait, ...] = Field(default=(), max_length=32)
    trait_model: Literal["authored-categorical-v1"] = "authored-categorical-v1"

    @model_validator(mode="after")
    def unique_traits(self) -> "Identity":
        if len({trait.key for trait in self.traits}) != len(self.traits):
            raise ValueError("An authored trait must occur only once.")
        return self


class Genesis(Contract):
    scope: Scope
    identity: Identity
    sim_minute: Sequence = 0


class Observe(Contract):
    kind: Literal["observe"] = "observe"
    record_id: Identifier
    text: Text
    source_kind: Literal["witnessed", "reported"]
    # These are host-assigned source identities, not model confidence or new facts.
    root_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=16)


class Citation(Contract):
    record_id: Identifier
    quote: Text


class Interpret(Contract):
    kind: Literal["interpret"] = "interpret"
    record_id: Identifier
    belief_id: Identifier
    statement: Text
    about_id: Identifier
    domain: Identifier
    stance: Literal["support", "challenge"]
    source_kind: Literal["inference", "reflection"] = "inference"
    citations: tuple[Citation, ...] = Field(min_length=1, max_length=16)


class Advance(Contract):
    kind: Literal["advance"] = "advance"


Payload = Annotated[Observe | Interpret | Advance, Field(discriminator="kind")]


class Event(Contract):
    scope: Scope
    event_id: Identifier
    sequence: Annotated[int, Field(ge=1, strict=True)]
    sim_minute: Sequence
    payload: Payload


class Evidence(Contract):
    id: Identifier
    text: Text
    source_kind: Literal["witnessed", "reported", "inference", "reflection"]
    root_ids: tuple[Identifier, ...]
    citations: tuple[Citation, ...] = ()
    event_id: Identifier


class Belief(Contract):
    id: Identifier
    statement: Text
    about_id: Identifier
    domain: Identifier
    revision: Annotated[int, Field(ge=1, strict=True)]
    interpretation_ids: tuple[Identifier, ...]
    support_roots: tuple[Identifier, ...] = ()
    challenge_roots: tuple[Identifier, ...] = ()
    status: Literal["tentative", "challenged"]
    # Evidence counts are not calibrated confidence. Unknown must stay unknown.
    probability: None = None


class Snapshot(Contract):
    schema_version: Literal[1] = 1
    transition_version: Literal["evidence-ledger-v1"] = "evidence-ledger-v1"
    genesis: Genesis
    revision: Sequence = 0
    cursor: Sequence = 0
    sim_minute: Sequence
    evidence: tuple[Evidence, ...] = Field(default=(), max_length=512)
    beliefs: tuple[Belief, ...] = Field(default=(), max_length=256)
    journal: tuple[Event, ...] = Field(default=(), max_length=512)


class Transition(Contract):
    snapshot: Snapshot
    duplicate: bool = False
    # New independent roots for this belief, not an increment of certainty.
    added_roots: tuple[Identifier, ...] = ()
