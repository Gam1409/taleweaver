"""Free deterministic blueprint preflight for the adventure generator."""

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from backend.core.auth import get_current_user
from backend.engine.blueprint import BlueprintError, analyze_blueprint, has_blueprint_tags
from backend.engine.blueprint.generation import prepare_generation_blueprint
from backend.engine.blueprint.options import BlueprintOptions
from backend.models.user import User

router = APIRouter(tags=["Adventure Creation"])


class BlueprintValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(default="", max_length=20_000)
    options: BlueprintOptions = Field(default_factory=BlueprintOptions)


@router.post("/blueprint/validate", response_model=None)
async def validate_blueprint(
    payload: BlueprintValidationRequest, user: User = Depends(get_current_user)
) -> dict[str, Any]:
    if not has_blueprint_tags(payload.text):
        return {"has_tags": False, "errors": [], "warnings": [], "counts": {}}
    parsed, _ = analyze_blueprint(payload.text)
    try:
        prepare_generation_blueprint(payload.text, payload.options.model_dump(exclude_none=True))
    except BlueprintError as exc:
        return {
            "has_tags": True,
            "errors": [e.as_dict() for e in exc.issues],
            "warnings": [e.as_dict() for e in parsed.warnings],
            "counts": {},
        }
    counts: dict[str, int] = {}
    for block in parsed.blocks:
        counts[block.kind] = counts.get(block.kind, 0) + 1
    return {
        "has_tags": True,
        "errors": [],
        "warnings": [e.as_dict() for e in parsed.warnings],
        "counts": counts,
    }
