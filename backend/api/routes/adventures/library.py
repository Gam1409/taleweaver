"""Adventure library API: browse ``library.json`` and install adventures from it.

SSRF boundary (CWE-918): no endpoint accepts a URL from the client. Requests carry
library entry ids only; file URLs are built server-side from
``settings.ADVENTURE_LIBRARY_URL`` and the validated index.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import get_current_user
from backend.core.database import get_db
from backend.engine.adventure_identity import stable_origin_id
from backend.engine.adventure_importer import AdventureConflictError
from backend.models.user import User
from backend.services.adventure_library import (
    AdventureInstallError,
    AdventureLibrary,
    LibraryEntry,
    LibraryError,
    LibraryItemView,
    LibraryService,
    install_entry,
    is_version_at_least,
    library_url,
)
from backend.services.adventure_library.installer import owned_templates

router = APIRouter(tags=["Adventures"])
logger = logging.getLogger(__name__)

_library_service = LibraryService()
# Entry ids with an install in flight; a second click must not import twice in parallel.
_installing: set[tuple[str, str]] = set()


class LibraryInstallRequest(BaseModel):
    """A library entry id; never a URL."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=200)


async def _installed_versions(
    db: AsyncSession, owner_id: str, origin_ids: list[str]
) -> dict[str, str | None]:
    """Map ``origin_id`` -> highest installed version of this owner, in one query."""
    if not origin_ids:
        return {}
    installed: dict[str, str | None] = {}
    for template in await owned_templates(db, owner_id, origin_ids):
        origin_id, version = stable_origin_id(template), template.version
        current = installed.get(origin_id)
        if current is None or is_version_at_least(version or "", current):
            installed[origin_id] = version
    return installed


def _item_view(entry: LibraryEntry, installed_version: str | None) -> LibraryItemView:
    update_available = installed_version is not None and not is_version_at_least(
        installed_version, entry.version
    )
    return LibraryItemView(
        entry=entry,
        cover_url=library_url(entry.slug, entry.cover) if entry.cover else None,
        installed_version=installed_version,
        update_available=update_available,
    )


async def _library_response(
    library: AdventureLibrary, db: AsyncSession, owner_id: str
) -> dict[str, Any]:
    installed = await _installed_versions(db, owner_id, [e.id for e in library.adventures])
    items = [_item_view(entry, installed.get(entry.id)) for entry in library.adventures]
    items.sort(key=lambda item: item.entry.title.casefold())
    return {
        "items": [item.model_dump(mode="json") for item in items],
        "stale": _library_service.is_stale(),
    }


async def _load_library(*, force_refresh: bool = False) -> AdventureLibrary:
    try:
        return await _library_service.get_library(force_refresh=force_refresh)
    except LibraryError as exc:
        logger.warning("Adventure library unavailable: %s", exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Adventure library unavailable") from exc


@router.get("/library/catalog")
async def get_library_catalog(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Return library entries merged with the caller's install state."""
    library = await _load_library()
    return await _library_response(library, db, current_user.id)


@router.post("/library/refresh")
async def refresh_library_catalog(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Bypass the cache, then return the same view as ``GET /library/catalog``."""
    library = await _load_library(force_refresh=True)
    return await _library_response(library, db, current_user.id)


@router.post("/library/install")
async def install_library_adventure(
    payload: LibraryInstallRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Download one adventure from the library and import it; returns when done."""
    entry = _library_service.resolve_entry(await _load_library(), payload.id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown library id: {payload.id}")
    install_key = (current_user.id, entry.id)
    if install_key in _installing:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{entry.title} is already being installed")

    _installing.add(install_key)
    try:
        template_id = await install_entry(db, entry, owner_id=current_user.id)
    except LibraryError as exc:
        logger.warning("Downloading %s failed: %s", entry.slug, exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Download failed: {exc}") from exc
    except AdventureInstallError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except AdventureConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{exc.title} already exists") from exc
    finally:
        _installing.discard(install_key)
    return {"template_id": template_id, "version": entry.version}
