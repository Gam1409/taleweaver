"""Report installation prerequisites without exposing endpoint URLs or credentials."""

from fastapi import APIRouter, Depends

from backend.core.auth import get_current_user
from backend.core.inference import admission
from backend.engine.living_world.concordia_adapter import available
from backend.engine.living_world.schema import Settings
from backend.models.user import User

router = APIRouter(tags=["Living World"])


@router.get("/living-world/capabilities")
async def capabilities(user: User = Depends(get_current_user)) -> dict:
    return {
        "concordia_available": available(),
        "inference_serialization_enabled": admission.enabled(),
        "defaults": Settings().model_dump(),
    }
