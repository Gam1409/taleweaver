"""Fence cancelled/replaced generation jobs before persisting their results."""

import asyncio
from contextvars import ContextVar
from typing import Any

from sqlalchemy import or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.adventure_template import AdventureTemplate, GenerationCancelled

generation_run: ContextVar[str | None] = ContextVar("generation_run", default=None)
_running_tasks: dict[str, asyncio.Task] = {}


def register_generation(template_id: str) -> None:
    task = asyncio.current_task()
    if task is not None:
        _running_tasks[template_id] = task


def unregister_generation(template_id: str) -> None:
    if _running_tasks.get(template_id) is asyncio.current_task():
        _running_tasks.pop(template_id, None)


def cancel_local_generation(template_id: str) -> None:
    task = _running_tasks.get(template_id)
    if task is not None and not task.done():
        task.cancel()


async def assert_generation_current(db: AsyncSession, adventure: AdventureTemplate) -> None:
    """Refresh the attempt token; old workers must never overwrite a resumed job."""
    await db.refresh(adventure, attribute_names=["generation_run_id", "creation_status"])
    expected = generation_run.get()
    if adventure.creation_status == "Cancelled":
        raise GenerationCancelled("Generation was cancelled by the user.")
    if expected is not None and adventure.generation_run_id != expected:
        raise GenerationCancelled("Generation was replaced by a newer attempt.")


async def guard_generation_write(
    db: AsyncSession, adventure: AdventureTemplate, **values: Any
) -> None:
    """Atomically fence a write and hold the row until its surrounding transaction commits."""
    expected = generation_run.get() or adventure.generation_run_id
    with db.no_autoflush:
        result = await db.execute(
            update(AdventureTemplate)
            .where(
                AdventureTemplate.id == adventure.id,
                AdventureTemplate.generation_run_id == expected,
                or_(
                    AdventureTemplate.creation_status.is_(None),
                    AdventureTemplate.creation_status != "Cancelled",
                ),
            )
            .values(**(values or {"generation_run_id": expected}))
            .execution_options(synchronize_session=False)
        )
    if result.rowcount != 1:
        raise GenerationCancelled("Generation was cancelled or replaced by a newer attempt.")
