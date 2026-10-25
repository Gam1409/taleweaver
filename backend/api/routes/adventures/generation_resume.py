"""Resume a failed generation without creating another adventure or session."""

from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.routes.adventures.adventure_creation import (
    CoverSource,
    GenerationJob,
    ensure_no_active_generation,
    run_background_generation,
)
from backend.api.routes.adventures.schemas import CreateAdventureTemplatePayload
from backend.core.auth import get_current_user
from backend.core.database import get_db
from backend.engine.generation_control import cancel_local_generation
from backend.models.adventure_template import AdventureTemplate
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.user import User

router = APIRouter(tags=["Adventures"])


def can_resume_generation(adventure: AdventureTemplate) -> bool:
    return bool(
        adventure.generation_request
        and not adventure.is_ready
        and adventure.creation_status in {"Failed", "Cancelled"}
    )


async def _resume_job(db: AsyncSession, adventure: AdventureTemplate) -> GenerationJob:
    saved = adventure.generation_request or {}
    session = await db.get(GameSession, saved.get("session_id", ""))
    if not session or session.template_id != adventure.id or session.user_id != adventure.owner_id:
        raise HTTPException(409, "The original generation session is no longer available.")
    played = await db.scalar(
        select(ChatMessage.id)
        .join(GameSession, ChatMessage.session_id == GameSession.id)
        .where(GameSession.template_id == adventure.id)
        .limit(1)
    )
    if played:
        raise HTTPException(409, "This adventure has gameplay history and cannot be regenerated.")
    source = None
    if saved.get("cover_source_id"):
        source = await db.get(AdventureTemplate, saved["cover_source_id"])
    return GenerationJob(
        payload=CreateAdventureTemplatePayload.model_validate(saved["payload"]),
        user_id=adventure.owner_id,
        template_id=adventure.id,
        session_id=session.id,
        selected_image_styles=saved.get("selected_image_styles"),
        cover=CoverSource(
            template=source,
            manifest=saved.get("cover_manifest"),
            name=saved.get("cover_name"),
            saved_id=saved.get("cover_source_id"),
        ),
        run_id=str(uuid4()),
    )


@router.post("/{template_id}/resume-generation")
async def resume_generation(
    template_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    adventure = await db.scalar(
        select(AdventureTemplate).where(
            AdventureTemplate.id == template_id, AdventureTemplate.owner_id == current_user.id
        )
    )
    if adventure is None:
        raise HTTPException(404, "AdventureTemplate not found.")
    if not can_resume_generation(adventure):
        raise HTTPException(409, "Only a stopped generation with a saved request can be resumed.")
    await ensure_no_active_generation(db, current_user.id)
    job = await _resume_job(db, adventure)
    # Compare-and-set prevents two simultaneous clicks from launching two workers.
    result = await db.execute(
        update(AdventureTemplate)
        .where(
            AdventureTemplate.id == template_id,
            AdventureTemplate.is_ready.is_(False),
            AdventureTemplate.creation_status.in_(["Failed", "Cancelled"]),
            AdventureTemplate.generation_run_id == adventure.generation_run_id,
        )
        .values(
            creation_status="Resuming saved generation...",
            creation_error=None,
            generation_run_id=job.run_id,
        )
    )
    if result.rowcount != 1:
        await db.rollback()
        raise HTTPException(409, "Generation is already resuming.")
    await db.commit()
    cancel_local_generation(template_id)
    background_tasks.add_task(run_background_generation, job)
    return {"adventure_id": template_id, "game_id": job.session_id, "status": "Resuming"}
