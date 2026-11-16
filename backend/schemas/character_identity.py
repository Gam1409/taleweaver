"""Optional character-card facts shared by editor and world manifests."""

from typing import Annotated

from pydantic import BaseModel, Field, StrictInt, StringConstraints


class CharacterIdentityFields(BaseModel):
    gender: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = None
    age_years: Annotated[StrictInt, Field(ge=0, le=100000)] | None = None
