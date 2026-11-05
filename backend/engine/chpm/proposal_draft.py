"""Wire proposals omit redundant goal judgments; derive them from cited motives."""

from typing import Any

from pydantic import Field, model_validator

from backend.engine.chpm.appraisal_contracts import (
    Assessment,
    FeltExperience,
    GroundedProposal,
    Grounds,
    Revision,
)
from backend.engine.chpm.core.contracts import Contract
from backend.engine.chpm.core.relationships import Domain
from backend.engine.chpm.development_contracts import Development, DevelopmentProposal
from backend.engine.chpm.motivation import Catalogue
from backend.engine.chpm.motivation_contracts import Motive
from backend.engine.chpm.schema import ActionKind, AgendaIntent, ChoicePreference, QuestionGate


class Intent(Contract):
    intention: str = Field(min_length=1, max_length=400)
    reconsider_if: str = Field(min_length=1, max_length=200)
    agenda_change: AgendaIntent | None = None
    motives: list[Motive] = Field(min_length=1, max_length=3)

    @model_validator(mode="before")
    @classmethod
    def retire_duplicate_judgments(cls, value: Any) -> Any:
        # Compatibility with older proposal producers. These fields have no
        # authority: the host always derives them from validated motive sources.
        if isinstance(value, dict):
            return {k: v for k, v in value.items() if k not in {"goal_alignment", "goal_quote"}}
        return value


class NewBelief(Grounds):
    about_id: str = Field(min_length=1, max_length=100)
    domain: Domain
    statement: str = Field(min_length=1, max_length=240)


class Draft(Contract):
    choice: ChoicePreference
    new_beliefs: list[NewBelief] = Field(max_length=2)
    belief_revisions: list[Revision] = Field(max_length=2)
    experiences: list[FeltExperience] = Field(default_factory=list, max_length=2)
    candidates: dict[ActionKind, Intent] = Field(min_length=2, max_length=4)
    question_gate: QuestionGate | None = None

    @model_validator(mode="after")
    def appraisal_budget(self) -> "Draft":
        if len(self.new_beliefs) + len(self.belief_revisions) > 2:
            raise ValueError("At most two new beliefs and revisions combined per turn.")
        return self

    def materialize(self, catalogue: Catalogue) -> GroundedProposal:
        body = self.model_dump(exclude={"new_beliefs", "belief_revisions"})
        body["interpretations"] = [
            Assessment(**item.model_dump()).model_dump() for item in self.new_beliefs
        ] + [item.model_dump() for item in self.belief_revisions]
        for kind, candidate in self.candidates.items():
            body["candidates"][kind].update(_goal(candidate, catalogue))
        schema = DevelopmentProposal if isinstance(self, DevelopmentDraft) else GroundedProposal
        return schema.model_validate(body)


class DevelopmentDraft(Draft):
    developments: list[Development] = Field(default_factory=list, max_length=1)


def _goal(candidate: Intent, catalogue: Catalogue) -> dict:
    goals = [
        (m.effect, catalogue.sources[m.motive_id].text)
        for m in candidate.motives
        if m.motive_id in catalogue.sources
        and catalogue.sources[m.motive_id].kind == "authored_goal"
    ]
    effects = {effect for effect, _ in goals}
    if len(effects) != 1 or not goals or any(len(text) > 300 for _, text in goals):
        return {"goal_alignment": "unknown", "goal_quote": ""}
    return {
        "goal_alignment": "supports" if goals[0][0] == "supports" else "conflicts",
        "goal_quote": sorted(text for _, text in goals)[0],
    }
