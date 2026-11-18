"""Generated proposals select references; legacy canonical readers keep exact quotations."""

from collections.abc import Sequence
from typing import ClassVar, Literal

from pydantic import AliasChoices, ConfigDict, Field, model_validator

from backend.engine.chpm import agenda_references, experience_schema, json_contract
from backend.engine.chpm.appraisal_contracts import Explanation, GroundedProposal
from backend.engine.chpm.core.contracts import Contract, ExperienceValue, Identifier
from backend.engine.chpm.core.limits import MAX_PROPOSED_FACT_CITATIONS
from backend.engine.chpm.core.relationships import Domain
from backend.engine.chpm.motivation import Catalogue
from backend.engine.chpm.proposal_draft import DevelopmentDraft, Draft
from backend.engine.chpm.quote_references import References
from backend.engine.chpm.schema import (
    ActionKind,
    AgendaEntry,
    IntentionCondition,
    Proposal,
    ProposalOptions,
    QuestionGate,
)

# Require a choice from generated candidates; legacy canonical readers keep their defaults.
_AGENDA_CHANGE_DESCRIPTION = (
    "Explicitly choose null or a spoken agenda change: goal/commitment for a continuing "
    "personal aim/undertaking stated in own speech; null for immediate acts, silent/private "
    "intent or no change. Closures select an active owned entry_id."
)


class ReferenceContract(Contract):
    model_config = ConfigDict(str_strip_whitespace=False)


class QuoteReference(ReferenceContract):
    fragment_id: str = Field(min_length=1, max_length=32)


class EpisodeReference(ReferenceContract):
    episode_id: Identifier


class Grounds(ReferenceContract):
    stance: Literal["support", "challenge"]
    citations: tuple[QuoteReference, ...] = Field(
        min_length=1, max_length=MAX_PROPOSED_FACT_CITATIONS
    )
    alternatives: tuple[Explanation, ...] = Field(max_length=2)
    unknowns: tuple[Explanation, ...] = Field(max_length=3)


class NewBelief(Grounds):
    about_id: Identifier
    domain: Domain
    statement: str = Field(min_length=1, max_length=240)


class Revision(Grounds):
    belief_id: Identifier


class Experience(ExperienceValue):
    model_config = ConfigDict(str_strip_whitespace=False, json_schema_extra=experience_schema.rules)
    citations: tuple[QuoteReference, ...] = Field(min_length=1, max_length=2)
    personal_motive_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=3)
    explanation: str = Field(min_length=1, max_length=180)
    alternatives: tuple[Explanation, ...] = Field(max_length=2)
    unknowns: tuple[Explanation, ...] = Field(max_length=3)


class Choice(ReferenceContract):
    preferred: ActionKind
    motive_ids: list[str] = Field(
        min_length=1, max_length=3, json_schema_extra={"uniqueItems": True}
    )
    reason: str = Field(min_length=1, max_length=300)
    continuity: Literal["new", "maintain", "revise"]
    change_basis: list[QuoteReference] = Field(default_factory=list, max_length=2)


class MotiveReference(ReferenceContract):
    motive_id: Identifier
    effect: Literal["supports", "tension"]
    relevance: str = Field(min_length=1, max_length=180)


class Intent(ReferenceContract):
    intention: str = Field(
        min_length=1,
        max_length=400,
        validation_alias=AliasChoices("message_plan", "intention"),
        serialization_alias="message_plan",
    )
    preconditions: list[IntentionCondition] = Field(max_length=2)
    reconsider_if: str = Field(min_length=1, max_length=200)
    agenda_change: agenda_references.AgendaReference | None = Field(
        description=_AGENDA_CHANGE_DESCRIPTION
    )
    motives: list[MotiveReference] = Field(min_length=1, max_length=3)


class ReferenceDraft(ReferenceContract):
    reference_wire: ClassVar[bool] = True
    reference_scope: Identifier
    choice: Choice
    new_beliefs: list[NewBelief] = Field(max_length=2)
    belief_revisions: list[Revision] = Field(max_length=2)
    experiences: list[Experience] = Field(default_factory=list, max_length=2)
    candidates: dict[ActionKind, Intent] = Field(min_length=2, max_length=4)
    question_gate: QuestionGate | None = None

    @model_validator(mode="after")
    def appraisal_budget(self) -> "ReferenceDraft":
        if len(self.new_beliefs) + len(self.belief_revisions) > 2:
            raise ValueError("At most two new beliefs and revisions combined per turn.")
        return self

    def materialize(
        self, catalogue: Catalogue, references: References, entries: Sequence[AgendaEntry]
    ) -> GroundedProposal:
        references.validate(self.reference_scope, catalogue.observer_id)
        json_contract.validate_identifiers(
            type(self),
            self.model_dump(mode="json"),
            {key: list(values) for key, values in references.identifiers.items()},
        )
        body = self.model_dump(exclude={"reference_scope"})
        for key in ("new_beliefs", "belief_revisions", "experiences"):
            for item in body[key]:
                item["citations"] = [references.quote(c["fragment_id"]) for c in item["citations"]]
        body["choice"]["change_basis"] = [
            references.quote(item["fragment_id"]) for item in body["choice"]["change_basis"]
        ]
        for kind, intent in self.candidates.items():
            resolved = agenda_references.materialize(
                intent.agenda_change, entries, catalogue.observer_id
            )
            body["candidates"][kind]["agenda_change"] = resolved.model_dump() if resolved else None
        if isinstance(self, ReferenceDevelopmentDraft):
            for item in body["developments"]:
                for key in ("citations", "counterexamples"):
                    item[key] = [references.episode(c["episode_id"]) for c in item[key]]
            return DevelopmentDraft.model_validate(body).materialize(catalogue)
        return Draft.model_validate(body).materialize(catalogue)


class Development(ReferenceContract):
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


class ReferenceDevelopmentDraft(ReferenceDraft):
    developments: list[Development] = Field(default_factory=list, max_length=1)


class GoalIntent(ReferenceContract):
    intention: str = Field(min_length=1, max_length=400)
    preconditions: list[IntentionCondition] = Field(default_factory=list, max_length=2)
    goal_alignment: Literal["supports", "neutral", "conflicts", "unknown"] = "unknown"
    goal_ref: Identifier | None = None
    reconsider_if: str = Field(min_length=1, max_length=200)
    agenda_change: agenda_references.AgendaReference | None = Field(
        description=_AGENDA_CHANGE_DESCRIPTION
    )


class GoalReferenceProposal(ReferenceContract):
    """Observe-mode intentions select the authored goal without copying its prose."""

    reference_wire: ClassVar[bool] = True
    reference_scope: Identifier
    candidates: dict[ActionKind, GoalIntent] = Field(min_length=2, max_length=4)
    appraisal: str = Field(max_length=300)

    def canonical(
        self, goal: str, entries: Sequence[AgendaEntry], actor_id: str, scope: str
    ) -> Proposal:
        if self.reference_scope != scope:
            raise ValueError("CHPM authored goal references another prepared source window.")
        body = self.model_dump(exclude={"reference_scope"})
        for kind, candidate in self.candidates.items():
            selected = candidate.goal_ref
            if selected is not None and (selected != "authored_goal" or not 0 < len(goal) <= 300):
                raise ValueError("CHPM selected an unavailable authored goal reference.")
            current = body["candidates"][kind]
            current.pop("goal_ref")
            current["goal_quote"] = goal if selected else ""
            resolved = agenda_references.materialize(candidate.agenda_change, entries, actor_id)
            current["agenda_change"] = resolved.model_dump() if resolved else None
        return ProposalOptions.model_validate(body).canonical()


INSTRUCTIONS = """
Copy reference_scope; select evidence by fragment_id and development by episode_id.
Never copy source quotations.
"""


def instructions(text: str) -> str:
    return (
        text.replace(
            "Cite visible source_id + exact quote.", "Select visible fragment_id citations."
        )
        .replace("(exact source_id/quote pairs)", "(visible fragment_id references)")
        .replace("and\nexact visible quotes.", "only.")
        .replace("brief text and entry_id=null", "brief text")
        .replace(
            "Closures: text=ACTIVE OWNED TEXT, not dialogue; entry_id=ACTIVE ID.",
            "Closures: entry_id=ACTIVE OWNED ID; the host supplies its text.",
        )
        + INSTRUCTIONS
    )
