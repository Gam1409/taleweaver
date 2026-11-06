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
APPRAISAL: new_beliefs and belief_revisions are required arrays ([] if unwarranted),
at most TWO entries combined. Omit obsolete appraisal/interpretations.
New entries: about_id, domain, statement; revisions: belief_id instead.
Both: stance, citations, alternatives, unknowns. Cite visible source_id + exact quote.
Support/challenge the STATEMENT, not the person/request; never rewrite it on revision.
Reconsider relevant existing beliefs rather than duplicating them. An explanation
can challenge suspicion without proving completion. Repeated grounds add no independent
confirmation. basis_for labels support/challenge of a belief, not truth of a report.
Domains stay distinct and subjective. No probabilities, trait edits
or world effects; empty alternatives/unknowns do not establish certainty.
Observed changes prove neither cause nor hidden intent. Not visible means neither
dead nor departed; missing recall proves no absence. Old fragments remain historical;
current host facts prevail. Feelings, arousal, fear, politeness and demands prove no agreement.
CLARIFY needs a decision-changing fact/player choice and two distinct answers mapped
to TWO OTHER keys; prefer useful independent action. Never invent stalling dependencies,
ask permission to speak or outsource this NPC's wishes. Contextual questions may express
care/curiosity/suspicion/negotiation, not habitual endings. Uncertainty need not cause refusal.
"""
