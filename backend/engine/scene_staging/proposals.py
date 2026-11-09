"""Validate independent staging proposals without weakening their domain contracts."""

from dataclasses import dataclass, field
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError

from .props import PropDelta
from .schema import ExplicitDelta, SceneDelta, SceneExtraction


class StagingProposal(BaseModel):
    """Evidence-backed visual changes to the current scene, using only supplied identities."""

    model_config = ConfigDict(extra="forbid")
    changes: Annotated[
        list[Any], BeforeValidator(lambda value: value, json_schema_input_type=list[SceneDelta])
    ] = Field(default_factory=list, max_length=13)
    props: Annotated[
        list[Any], BeforeValidator(lambda value: value, json_schema_input_type=list[PropDelta])
    ] = Field(default_factory=list, max_length=24)
    explicit: Annotated[
        list[Any], BeforeValidator(lambda value: value, json_schema_input_type=list[ExplicitDelta])
    ] = Field(default_factory=list, max_length=8)


@dataclass
class ValidatedStaging:
    value: SceneExtraction
    unconfirmed_actors: set[str] = field(default_factory=set)
    rejected: dict[str, int] = field(default_factory=dict)


def validate(proposal: Any) -> ValidatedStaging:
    raw = proposal.model_dump() if isinstance(proposal, BaseModel) else proposal
    bounded = StagingProposal.model_validate(raw)
    sections: dict[str, list[BaseModel]] = {}
    rejected = {}
    unconfirmed: set[str] = set()
    for name, contract in (
        ("changes", SceneDelta),
        ("props", PropDelta),
        ("explicit", ExplicitDelta),
    ):
        sections[name], rejected[name], actors = _section(getattr(bounded, name), contract)
        if name == "changes":
            unconfirmed.update(actors)
    return ValidatedStaging(SceneExtraction.model_validate(sections), unconfirmed, rejected)


def _section(
    entries: list[Any], contract: type[BaseModel]
) -> tuple[list[BaseModel], int, set[str]]:
    accepted = []
    unconfirmed = set()
    rejected = 0
    for entry in entries:
        try:
            accepted.append(contract.model_validate(entry))
        except ValidationError:
            rejected += 1
            actor = entry.get("entity_id") if isinstance(entry, dict) else None
            if isinstance(actor, str) and 0 < len(actor) <= 100:
                unconfirmed.add(actor)
    return accepted, rejected, unconfirmed
