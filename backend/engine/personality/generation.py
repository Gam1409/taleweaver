"""Strict new-world profile contract, separate from backwards-compatible imports."""

from pydantic import Field, create_model, model_validator

from backend.engine.personality.profile import CATALOG, PersonalityProfile
from backend.engine.world_schemas import WorldNPCSchema


class CompleteProfile(PersonalityProfile):
    @model_validator(mode="after")
    def require_all_choices(self):
        if any(not value for value in self.model_dump().values()):
            raise ValueError("New NPCs require all seven personality choices")
        return self


GeneratedPersonalityProfile = create_model(
    "GeneratedPersonalityProfile",
    __base__=CompleteProfile,
    **{
        key: (str, Field(..., json_schema_extra={"enum": list(options)}))
        for key, (_, options) in CATALOG.items()
    },
)


class GeneratedNPCSchema(WorldNPCSchema):
    personality_profile: GeneratedPersonalityProfile = Field(
        ..., description="All seven personality tendencies, consistent with biography and goal."
    )
