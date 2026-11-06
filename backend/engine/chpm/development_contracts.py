"""Optional consolidation proposals are enabled only after sufficient dated history."""

from typing import Literal

from pydantic import Field

from backend.engine.chpm.appraisal_contracts import Explanation, GroundedProposal
from backend.engine.chpm.core.contracts import Contract, Identifier
from backend.engine.chpm.core.relationships import Domain


class EpisodeReference(Contract):
    episode_id: Identifier
    quote: str = Field(min_length=1, max_length=200)


class Development(Contract):
    category: Literal["habit", "relationship", "trait"]
    about_id: Identifier | None = None
    trait_key: Identifier | None = None
    relationship_domain: Domain | None = None
    statement: str = Field(min_length=1, max_length=240)
    existing_id: Identifier | None = None
    stance: Literal["support", "challenge"] = "support"
    citations: tuple[EpisodeReference, ...] = Field(min_length=3, max_length=6)
    counterexamples: tuple[EpisodeReference, ...] = Field(default=(), max_length=3)
    alternatives: tuple[Explanation, ...] = Field(min_length=1, max_length=2)
    unknowns: tuple[Explanation, ...] = Field(min_length=1, max_length=3)


class DevelopmentProposal(GroundedProposal):
    developments: list[Development] = Field(default_factory=list, max_length=1)
