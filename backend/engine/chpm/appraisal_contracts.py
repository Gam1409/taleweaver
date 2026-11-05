"""A bounded cognitive proposal, never a patch to personality, trust or world state."""

from typing import Annotated, Literal

from pydantic import Field

from backend.engine.chpm.core.contracts import Contract, ExperienceValue, Identifier
from backend.engine.chpm.core.relationships import Domain
from backend.engine.chpm.motivation_contracts import Motive
from backend.engine.chpm.schema import (
    ActionKind,
    Candidate,
    CandidateBody,
    ChoicePreference,
    Proposal,
    QuestionGate,
)

Explanation = Annotated[str, Field(min_length=1, max_length=160)]


class Reference(Contract):
    source_id: str = Field(min_length=1, max_length=100)
    quote: str = Field(min_length=1, max_length=300)


class Grounds(Contract):
    stance: Literal["support", "challenge"]
    citations: tuple[Reference, ...] = Field(min_length=1, max_length=2)
    alternatives: tuple[Explanation, ...] = Field(max_length=2)
    unknowns: tuple[Explanation, ...] = Field(max_length=3)


class Assessment(Grounds):
    about_id: str = Field(min_length=1, max_length=100)
    domain: Domain
    statement: str = Field(min_length=1, max_length=240)
    belief_id: None = None


class Revision(Grounds):
    belief_id: str = Field(min_length=1, max_length=100)


class MotivatedCandidate(CandidateBody):
    motives: list[Motive] = Field(min_length=1, max_length=3)


class FeltExperience(ExperienceValue):
    citations: tuple[Reference, ...] = Field(min_length=1, max_length=2)
    personal_motive_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=3)
    explanation: str = Field(min_length=1, max_length=180)
    alternatives: tuple[Explanation, ...] = Field(max_length=2)
    unknowns: tuple[Explanation, ...] = Field(max_length=3)


class GroundedProposal(Contract):
    choice: ChoicePreference | None = None
    # Required in live mode: a deliberate empty result is distinct from a model
    # silently ignoring this stage. Old saved Decisions retain their old schema.
    interpretations: list[Assessment | Revision] = Field(max_length=2)
    experiences: list[FeltExperience] = Field(default_factory=list, max_length=2)
    candidates: dict[ActionKind, MotivatedCandidate] = Field(min_length=2, max_length=4)
    question_gate: QuestionGate | None = None

    def canonical(self) -> Proposal:
        return Proposal(
            candidates=[
                Candidate(kind=kind, **body.model_dump(exclude={"motives"}))
                for kind, body in sorted(self.candidates.items())
            ],
            appraisal=f"Source-bound interpretations proposed: {len(self.interpretations)}.",
        )


INSTRUCTIONS = """
APPRAISAL: Return interpretations (0-2, [] if unwarranted), candidates, optional
question_gate; omit obsolete appraisal. Known-subject reliability, competence,
benevolence, affection and boundaries are distinct subjective domains.
Cite visible source_id plus exact contiguous quote. NEW beliefs have about_id,
domain, statement, belief_id=null. Revisions have ONLY belief_id, stance, citations,
alternatives, unknowns: support/challenge the original proposition without rewriting
it. No duplicate beliefs, probabilities, trait edits or world effects. Alternatives
and unknowns preserve uncertainty; empty lists do not prove certainty.
Witnessed state changes establish neither cause nor hidden intent. Not visible
means neither dead nor departed. Missing recall/data establishes no absence.
Old fragments remain historical, not fresh evidence; current host facts prevail.
Reported feelings, arousal, fear, politeness and demands do not prove agreement.
CLARIFY needs a decision-changing external fact or the player's undecided choice,
with two distinct answers mapped to TWO OTHER candidate keys. Prefer an equally
useful independent action. Do not invent dependencies to stall or ask the player
to choose this NPC's wishes/permission to speak. Contextual social questions may
instead express curiosity/care/suspicion/negotiation when they advance the selected
intention; do not append them habitually. Uncertainty need not cause refusal.
"""
