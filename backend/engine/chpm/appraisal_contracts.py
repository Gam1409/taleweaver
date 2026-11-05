"""A bounded cognitive proposal, never a patch to personality, trust or world state."""

from typing import Annotated, Literal

from pydantic import Field

from backend.engine.chpm.core.contracts import Contract, ExperienceValue, Identifier
from backend.engine.chpm.core.relationships import Domain
from backend.engine.chpm.motivation_contracts import Motive
from backend.engine.chpm.schema import ActionKind, Candidate, CandidateBody, Proposal, QuestionGate

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
APPRAISAL: Return interpretations (0-2, [] when unwarranted), candidates and optional
question_gate. Do not return the obsolete free-text appraisal. Assess expectations
about a known subject in reliability, competence, benevolence, affection or
boundaries; these domains are independent. Reports of feelings/consent are not
proof of them; arousal, politeness, fear and demands cannot establish agreement.

Cite a visible source_id and an exact contiguous quote inside its exposed excerpt.
For NEW beliefs use about_id/domain/statement and belief_id=null. For revisions,
return ONLY belief_id, stance, citations, alternatives and unknowns; the host keeps
the original proposition. Support or challenge it rather than rewriting history.
No duplicate propositions, probabilities, trait edits or world effects. Brief
alternatives/unknowns retain ambiguity; empty lists do not establish certainty.

Witnessed differences confirm only changed host state, not cause or intent.
No longer visible does not prove departure/death. Unknown/omitted data do not mean
none. Old recollections retain their source IDs and are historical fragments,
not new confirmation. Never fill gaps or infer no event from a recall miss.
Retrieval relevance is not truth. Current host facts override old observations.

Choose intentions from character, goals and tentative interpretations; uncertainty
does not require refusal or clarification. Independent progress is welcome.
CLARIFY needs a concrete external fact or player's own undecided intention, plus
two distinct answer branches referencing two other candidate keys whose choice
actually depends on that answer. An equally useful independent option takes
priority. Permission to speak/write, choose the NPC's wishes or express an already
selected intention is never such a gap. Do not invent dependencies or relabel
stalling as INITIATE. A contextual social question can be INITIATE/CONTINUE/NEGOTIATE
when it advances curiosity, care, suspicion or another personal purpose; do not
append questions habitually. Player choices still belong to the player.
"""
