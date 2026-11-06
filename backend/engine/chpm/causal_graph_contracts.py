"""Explicitly attributed influence links; report order alone never establishes causation."""

from typing import Literal

from pydantic import Field, model_validator

from backend.engine.chpm.core.contracts import Contract

FactKey = Literal["purpose", "cause", "event", "consequence", "next_step"]
Relation = Literal["motivates", "causes", "enables", "changes", "resolves"]
Attribution = Literal["explicit", "inferred"]
MAX_LINKS = 3


class LinkDraft(Contract):
    source: FactKey
    target: FactKey
    relation: Relation
    attribution: Attribution = "inferred"
    passage_id: str = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def distinct_fields(self) -> "LinkDraft":
        if self.source == self.target:
            raise ValueError("An influence must connect distinct statements.")
        return self


class Binding(Contract):
    thread_id: str = Field(min_length=1, max_length=64)
    parents: tuple[str, ...] = Field(min_length=1, max_length=5)
    quote: str = Field(min_length=1, max_length=600)
    field: FactKey | None = None
    relation: Relation | None = None
    attribution: Attribution | None = None
    action: Literal["open", "update", "close"] | None = None
    previous: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def fact_or_relation(self) -> "Binding":
        if self.action is not None:
            if (
                len(self.parents) < 2
                or len(set(self.parents)) != len(self.parents)
                or self.field is not None
                or self.relation is not None
                or self.attribution is not None
            ):
                raise ValueError("A causal transition needs distinct current fact nodes.")
            return self
        if self.previous is not None:
            raise ValueError("Only transitions can link to a previous transition.")
        if self.field is not None:
            if len(self.parents) != 1 or self.relation is not None or self.attribution is not None:
                raise ValueError("A causal statement needs one narration parent, not an edge.")
            return self
        if (
            len(self.parents) != 2
            or len(set(self.parents)) != 2
            or self.relation is None
            or self.attribution is None
        ):
            raise ValueError("An influence needs two distinct statement parents and attribution.")
        return self
