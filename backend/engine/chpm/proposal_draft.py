"""Wire proposals omit redundant goal judgments; derive them from cited motives."""

from typing import Any

from pydantic import Field, model_validator

from backend.engine.chpm.appraisal_contracts import (
    Assessment,
    FeltExperience,
    GroundedProposal,
    Revision,
)
from backend.engine.chpm.core.contracts import Contract
from backend.engine.chpm.development_contracts import Development, DevelopmentProposal
from backend.engine.chpm.motivation import Catalogue
from backend.engine.chpm.motivation_contracts import Motive
from backend.engine.chpm.schema import ActionKind, AgendaIntent, QuestionGate


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


class Draft(Contract):
    interpretations: list[Assessment | Revision] = Field(max_length=2)
    experiences: list[FeltExperience] = Field(default_factory=list, max_length=2)
    candidates: dict[ActionKind, Intent] = Field(min_length=2, max_length=4)
    question_gate: QuestionGate | None = None

    def materialize(self, catalogue: Catalogue) -> GroundedProposal:
        body = self.model_dump()
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
