"""Explicit item authoring repairs use bounded existing model and image roles."""

import asyncio
import json

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.llm_router import GameMasterLLM
from backend.engine.character_identity import identity_facts
from backend.engine.clothing.authoring import GARMENT_INSTRUCTION
from backend.engine.clothing.recovery_policy import classify_garment
from backend.engine.clothing.visuals import detailed_for_state
from backend.engine.image_profiles import image_timeout
from backend.engine.item_repair_contracts import REPAIR_PROMPT, RepairApply, RepairValues
from backend.engine.item_repair_store import ItemContext
from backend.engine.media_engine import MediaEngine
from backend.engine.session_portraits import _image_request as session_image_request
from backend.engine.session_portraits import _settings as session_image_settings
from backend.models.user import User


async def propose(user: User, item: dict, instruction: str, session_id: str) -> RepairValues:
    model = GameMasterLLM.for_role(user, "complex")
    model.enable_thinking = False
    model.max_tokens = min(model.max_tokens, 4096)
    result = await asyncio.wait_for(
        model.aexecute_complex_task(
            REPAIR_PROMPT + GARMENT_INSTRUCTION,
            json.dumps({"item": item, "author_request": instruction}, ensure_ascii=False),
            RepairValues,
            model.model,
            game_id=session_id,
            operation="item_repair",
            phase="preview",
        ),
        timeout=float(model.request_timeout),
    )
    return RepairValues.model_validate(result)


def validate_technical(context: ItemContext, request: RepairApply) -> None:
    if "technical" not in request.parts or request.values.clothing is None:
        return
    original = context.read()
    garment = classify_garment(
        original["name"], classify_garment(request.values.name, request.values.clothing)
    )
    request.values.clothing = garment
    if not garment.underwear:
        return
    owners = {row["owner"] for row in context.representations()} - {"__world__"}
    actors = {entity.id: entity for entity in context.entities if entity.entity_type == "NPC"}
    actors.update({"__player__": context.avatar, "__equipment__": context.avatar})
    ages = [identity_facts(actors[owner]).get("age_years") for owner in owners if owner in actors]
    if (
        not detailed_for_state(context.state)
        or not ages
        or any(type(age) is not int or age < 18 for age in ages)
    ):
        raise HTTPException(
            422,
            "Inner clothing metadata requires detailed clothing and an established adult owner. You can apply text or image repairs separately.",
        )


async def generate_image(db: AsyncSession, context: ItemContext, user: User) -> str:
    item = context.read()
    t2i, style, tone = await session_image_settings(db, context.state, user, "object")
    game_id = context.state.session_id
    request = session_image_request(game_id, item, t2i, user, style, tone, kind="object")
    await db.commit()  # Do not hold a SQLite read transaction during generation.
    result = await asyncio.wait_for(
        MediaEngine.generate_image(**request), timeout=image_timeout(t2i)
    )
    if not result:
        raise HTTPException(502, "No item image was returned. The previous image was kept.")
    return result
