"""Suggest missing garment properties for review; never mutate items or outfits."""

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.routes.adventures.editing.common import _get_owned_adventure_or_404
from backend.api.routes.adventures.editing.item_generation import Slot, _generate
from backend.core.auth import get_current_user
from backend.core.database import get_db
from backend.engine.clothing.authoring import validate_partial_garment
from backend.engine.clothing.schema import Garment
from backend.models.user import User

router = APIRouter(tags=["Editor"])


class GarmentPreparationRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=50)
    description: str = Field(default="", max_length=1000)
    wearable_slots: list[Slot] = Field(default_factory=list, max_length=12)
    clothing: dict[str, Any] = Field(default_factory=dict)

    @field_validator("clothing")
    @classmethod
    def valid_existing_fields(cls, value: dict) -> dict:
        return validate_partial_garment(value)


@router.post("/{template_id}/editor/prepare-clothing", response_model=Garment)
async def prepare_clothing(
    template_id: str,
    payload: GarmentPreparationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Garment | None:
    adventure = await _get_owned_adventure_or_404(db, template_id, current_user.id)
    if {"category", "layer", "coverage", "opaque"}.issubset(payload.clothing):
        return Garment.model_validate(payload.clothing)
    result = await _generate(
        current_user,
        {"theme": adventure.original_prompt or "", "item_type": "WEARABLE", **payload.model_dump()},
        Garment,
    )
    return Garment.model_validate({**result.model_dump(), **payload.clothing})
