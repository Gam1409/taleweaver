"""Publish imported worlds only after persistence and asset preparation succeed."""

from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Concatenate, ParamSpec

from anyio import CancelScope
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
_KEY = "adventure_import_transaction"
P = ParamSpec("P")


@dataclass
class ImportTransaction:
    created: set[str] = field(default_factory=set)
    replaced: set[str] = field(default_factory=set)


def register_created(db: AsyncSession, template_id: str) -> None:
    transaction = db.info.get(_KEY)
    if transaction is not None:
        transaction.created.add(template_id)


def defer_replacement(db: AsyncSession, template_id: str) -> bool:
    transaction = db.info.get(_KEY)
    if transaction is None:
        return False
    transaction.replaced.add(template_id)
    return True


async def _cleanup(template_ids: set[str]) -> None:
    from backend.engine.media_engine import MediaEngine

    for template_id in template_ids:
        try:
            await MediaEngine.cleanup_adventure_assets(template_id)
        except Exception:
            logger.exception("Import asset cleanup failed for %s", template_id)


def atomic_import(
    function: Callable[Concatenate[AsyncSession, P], Awaitable[bool]],
) -> Callable[Concatenate[AsyncSession, P], Awaitable[bool]]:
    """Defer replacement until the new world is ready; compensate failed asset writes."""

    @functools.wraps(function)
    async def wrapped(db: AsyncSession, *args: P.args, **kwargs: P.kwargs) -> bool:
        if _KEY in db.info:
            return await function(db, *args, **kwargs)
        transaction = ImportTransaction()
        db.info[_KEY] = transaction
        committed = False
        try:
            success = await function(db, *args, **kwargs)
            if not success:
                return False
            from backend.engine.gameplay.world import AdventureLogic

            for template_id in transaction.replaced:
                await AdventureLogic.delete_adventure(db, template_id, commit=False)
            await db.commit()
            committed = True
            await _cleanup(transaction.replaced)
            return True
        finally:
            db.info.pop(_KEY, None)
            if not committed:
                with CancelScope(shield=True):
                    await db.rollback()
                    await _cleanup(transaction.created)

    return wrapped
