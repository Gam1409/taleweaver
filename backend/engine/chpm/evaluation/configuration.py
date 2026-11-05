"""Read existing roles or build a temporary endpoint configuration; never save it."""

from collections.abc import Callable

from sqlalchemy import select

from backend.core.database import AsyncSessionLocal
from backend.core.llm_router import GameMasterLLM
from backend.models.user import User


async def factory_for(
    user_name: str | None, endpoint: str | None, model: str | None
) -> Callable[[str], GameMasterLLM]:
    if endpoint:
        user = await _temporary_user(endpoint, model)
    else:
        async with AsyncSessionLocal() as db:
            saved_user = await db.scalar(select(User).where(User.username == user_name))
            if saved_user is None:
                raise ValueError("Evaluation account was not found.")
            user = saved_user
    return lambda role: GameMasterLLM.for_role(user, role)


async def _temporary_user(endpoint: str, model: str | None) -> User:
    from backend.core.custom_openai import discover_models

    if not model:
        available = await discover_models(endpoint, None)
        if len(available) != 1:
            raise ValueError(
                "Supply --model when the endpoint does not advertise exactly one model."
            )
        model = available[0]
    # Existing URL validation, shared admission, and provider routing still apply.
    # This object is never added to a DB session or given saved credentials.
    return User(
        username="chpm-evaluation",
        encrypted_api_keys={},
        llm_settings={
            "custom_openai_url": endpoint,
            "custom_openai_response_format": "prompt",
            "small_model_provider": "custom_openai",
            "complex_model_provider": "custom_openai",
            "small_model": model,
            "complex_model": model,
            "small_max_tokens": 4096,
            "complex_max_tokens": 4096,
        },
    )
