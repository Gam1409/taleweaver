"""Opt-in candidate cardinality for a grounded live decision and its internal drafts."""

from functools import cache
from typing import Any, TypeVar

from pydantic import BaseModel, Field, create_model, model_validator

T = TypeVar("T", bound=BaseModel)


@model_validator(mode="after")
def _chosen_candidates(value: Any) -> Any:
    if value.choice is None:
        raise ValueError("A compact decision requires an explicit choice.")
    preferred = value.choice.preferred
    keys = set(value.candidates)
    if preferred != "CLARIFY":
        if keys != {preferred} or value.question_gate is not None:
            raise ValueError("Submit only the preferred candidate and omit the question gate.")
        return value
    gate = value.question_gate
    branches = {b.action for b in gate.branches} if gate else set()
    if len(branches) != 2 or "CLARIFY" in branches or keys != {"CLARIFY", *branches}:
        raise ValueError("CLARIFY needs its question gate and exactly the two branch candidates.")
    return value


@cache
def schema_for(base: type[T]) -> type[T]:
    # Keep each workflow's typed actions, development fields, and validators.
    # Only the candidate count differs across these fixed, process-wide schemas.
    fields: dict[str, Any] = {
        "candidates": (
            base.model_fields["candidates"].annotation,
            Field(min_length=1, max_length=3),
        ),
    }
    validators: dict[str, Any] = {"chosen_candidates": _chosen_candidates}
    return create_model(
        f"Compact{base.__name__}",
        __base__=base,
        __validators__=validators,
        **fields,
    )
