"""Bounded explanations tied to host-owned sources, not numerical utility."""

from typing import Literal

from pydantic import Field

from backend.engine.chpm.core.contracts import Contract


class Motive(Contract):
    motive_id: str = Field(min_length=1, max_length=100)
    effect: Literal["supports", "tension"]
    relevance: str = Field(min_length=1, max_length=180)


class MotiveSource(Contract):
    id: str = Field(min_length=1, max_length=100)
    kind: Literal[
        "authored_character",
        "authored_goal",
        "authored_trait",
        "authored_value",
        "authored_role",
        "declared_goal",
        "commitment",
        "report",
        "world_observation",
        "subjective_belief",
    ]
    text: str = Field(min_length=1, max_length=2000)
    provenance_id: str = Field(min_length=1, max_length=100)
    subject_id: str = Field(min_length=1, max_length=100)
    status: Literal["authored", "declared", "reported", "tentative", "challenged", "witnessed"]


class ResolvedMotive(Contract):
    source: MotiveSource
    effect: Literal["supports", "tension"]
    relevance: str = Field(min_length=1, max_length=180)
