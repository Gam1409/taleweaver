"""Source-bound subjective state, not a claim of calibrated human psychology."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .limits import ACTIVE_EVENTS, ARCHIVE_BLOCK, MAX_BELIEFS, MAX_EVENTS, MAX_EXPERIENCES
from .log_layout import split

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
    alternatives: tuple[Text, ...] = Field(default=(), max_length=2)
    unknowns: tuple[Text, ...] = Field(default=(), max_length=3)


class Advance(Contract):
    kind: Literal["advance"] = "advance"


class ExperienceValue(Contract):
    channel: Literal["affect", "need_satisfaction", "need_frustration"]
    dimension: Literal[
        "fear",
        "anger",
        "sadness",
        "joy",
        "shame",
        "interest",
        "arousal",
        "autonomy",
        "competence",
        "relatedness",
        "rest",
        "safety",
    ]
    about_id: Identifier | None = None
    level: Literal["absent", "low", "moderate", "high"]

    @model_validator(mode="after")
    def valid_dimension(self) -> "ExperienceValue":
        affect = self.dimension in {
            "fear",
            "anger",
            "sadness",
            "joy",
            "shame",
            "interest",
            "arousal",
        }
        if (self.channel == "affect") != affect:
            raise ValueError("Experience dimension does not match its channel.")
        if self.channel != "affect" and self.about_id is not None:
            raise ValueError("Needs describe the observer, not another person's state.")
        return self


class PersonalBasis(Contract):
    reference: Identifier
    text: Text


class Experience(ExperienceValue):
    kind: Literal["experience"] = "experience"
    policy: Literal["qualitative-experience-v1"] = "qualitative-experience-v1"
    record_id: Identifier
    identity_revision: Identifier
    citations: tuple[Citation, ...] = Field(min_length=1, max_length=2)
    personal_basis: tuple[PersonalBasis, ...] = Field(min_length=1, max_length=3)
    explanation: Annotated[str, Field(min_length=1, max_length=180)]
    alternatives: tuple[Text, ...] = Field(default=(), max_length=2)
    unknowns: tuple[Text, ...] = Field(default=(), max_length=3)


class ExperienceState(ExperienceValue):
    record_id: Identifier
    sim_minute: Sequence


Payload = Annotated[Observe | Interpret | Experience | Advance, Field(discriminator="kind")]


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
    alternatives: tuple[Text, ...] = ()
    unknowns: tuple[Text, ...] = ()


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


class EventArchive(Contract):
    events: tuple[Event, ...] = Field(min_length=ARCHIVE_BLOCK, max_length=ARCHIVE_BLOCK)


class Snapshot(Contract):
    schema_version: Literal[3] = 3
    transition_version: Literal["evidence-ledger-v2"] = "evidence-ledger-v2"
    genesis: Genesis
    revision: Sequence = 0
    cursor: Sequence = 0
    sim_minute: Sequence
    evidence: tuple[Evidence, ...] = Field(default=(), max_length=MAX_EVENTS)
    beliefs: tuple[Belief, ...] = Field(default=(), max_length=MAX_BELIEFS)
    experiences: tuple[ExperienceState, ...] = Field(default=(), max_length=MAX_EXPERIENCES)
    archive: tuple[EventArchive, ...] = Field(
        default=(), max_length=(MAX_EVENTS - ACTIVE_EVENTS) // ARCHIVE_BLOCK
    )
    journal: tuple[Event, ...] = Field(default=(), max_length=ACTIVE_EVENTS)

    @model_validator(mode="before")
    @classmethod
    def migrate_pilot_snapshot(cls, value: Any) -> Any:
        if not isinstance(value, dict) or value.get("schema_version") not in (1, 2):
            return value
        if value.get("transition_version", "evidence-ledger-v1") != "evidence-ledger-v1":
            raise ValueError("Unsupported legacy transition version.")
        if value["schema_version"] == 1:
            if (
                value.get("archive")
                or len(value.get("journal", ())) > 512
                or len(value.get("evidence", ())) > 512
                or len(value.get("beliefs", ())) > 256
            ):
                raise ValueError("Invalid legacy event layout.")
            blocks, journal = split(tuple(value.get("journal", ())))
            value = {
                **value,
                "archive": [{"events": block} for block in blocks],
                "journal": journal,
            }
        # The pilot shipped Experience before its version bump. Preserve those
        # events and projections too; restore() still verifies them by exact replay.
        return {
            **value,
            "schema_version": 3,
            "transition_version": "evidence-ledger-v2",
        }


class Transition(Contract):
    snapshot: Snapshot
    duplicate: bool = False
    # New independent roots for this belief, not an increment of certainty.
    added_roots: tuple[Identifier, ...] = ()
