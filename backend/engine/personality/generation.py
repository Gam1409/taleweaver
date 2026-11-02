"""Strict new-world profile contract, separate from backwards-compatible imports."""

from pydantic import Field, model_validator
from typing_extensions import Self

from backend.engine.personality.profile import CATALOG, PersonalityProfile
from backend.engine.world_schemas import WorldNPCSchema


class CompleteProfile(PersonalityProfile):
    @model_validator(mode="after")
    def require_all_choices(self) -> Self:
        if any(not value for value in self.model_dump().values()):
            raise ValueError("New NPCs require all seven personality choices")
        return self


class GeneratedPersonalityProfile(CompleteProfile):
    temperament: str = Field(..., json_schema_extra={"enum": list(CATALOG["temperament"][1])})
    sociability: str = Field(..., json_schema_extra={"enum": list(CATALOG["sociability"][1])})
    speech: str = Field(..., json_schema_extra={"enum": list(CATALOG["speech"][1])})
    trust: str = Field(..., json_schema_extra={"enum": list(CATALOG["trust"][1])})
    value: str = Field(..., json_schema_extra={"enum": list(CATALOG["value"][1])})
    conflict: str = Field(..., json_schema_extra={"enum": list(CATALOG["conflict"][1])})
    risk: str = Field(..., json_schema_extra={"enum": list(CATALOG["risk"][1])})


class GeneratedNPCSchema(WorldNPCSchema):
    personality_profile: GeneratedPersonalityProfile = Field(
        ..., description="All seven personality tendencies, consistent with biography and goal."
    )
