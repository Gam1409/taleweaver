"""Install a converted catalog release as a new template without touching saved games."""

from __future__ import annotations

import asyncio
import io
import json
import zipfile
from uuid import UUID

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.engine.adventure_compat import CompatibilityError, import_upstream_manifest
from backend.engine.adventure_identity import stable_origin_id
from backend.engine.adventure_importer import MAX_ADZ_ENTRY_BYTES, AdventureTemplateImporter
from backend.models.adventure_template import AdventureTemplate
from backend.services.adventure_library.catalog import library_url
from backend.services.adventure_library.downloads import (
    ByteBudget,
    LibraryError,
    client_context,
    fetch_bytes,
)
from backend.services.adventure_library.models import (
    BLUEPRINT_NAME,
    LibraryEntry,
    is_version_at_least,
    version_tuple,
)

FETCH_CONCURRENCY = 8


class AdventureInstallError(Exception):
    """A catalog release has invalid identity, unsupported semantics or invalid assets."""


async def fetch_files(
    entry: LibraryEntry, http_client: httpx.AsyncClient | None = None
) -> dict[str, bytes]:
    budget = ByteBudget(settings.ADVENTURE_DOWNLOAD_MAX_BYTES)
    if entry.size_bytes > budget.limit:
        raise LibraryError("Adventure exceeds the configured download limit")
    semaphore = asyncio.Semaphore(FETCH_CONCURRENCY)

    async def fetch_one(client: httpx.AsyncClient, path: str) -> bytes:
        async with semaphore:
            return await fetch_bytes(
                client, library_url(entry.slug, path), budget, MAX_ADZ_ENTRY_BYTES
            )

    async with client_context(http_client) as client:
        tasks = [asyncio.create_task(fetch_one(client, path)) for path in entry.files]
        try:
            contents = await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    return dict(zip(entry.files, contents, strict=True))


def build_bundle(files: dict[str, bytes]) -> bytes:
    """Keep an assembled download uncompressed to avoid artificial zip-ratio rejection."""
    names = sorted(files, key=lambda name: (name != BLUEPRINT_NAME, name))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name in names:
            archive.writestr(name, files[name])
    return buffer.getvalue()


def convert_files(entry: LibraryEntry, files: dict[str, bytes]) -> dict[str, bytes]:
    """Bind downloaded identity/version/title to the selected index before conversion."""
    try:
        payload = json.loads(files[BLUEPRINT_NAME])
        adventure = payload["adventure"]
        origin = str(UUID(str(adventure["origin_id"])))
        top_origin = payload.get("origin_id")
        if top_origin and str(UUID(str(top_origin))) != origin:
            raise ValueError("Conflicting manifest identities")
        if (origin, adventure.get("version"), adventure.get("title")) != (
            entry.id,
            entry.version,
            entry.title,
        ):
            raise ValueError(
                "Downloaded adventure identity, version or title differs from the catalog"
            )
        asset_names = [
            path.rsplit("/", 1)[-1].casefold() for path in files if path.startswith("assets/")
        ]
        if len(asset_names) != len(set(asset_names)):
            raise ValueError("Assets with duplicate filenames cannot be imported safely")
        converted = import_upstream_manifest(payload)
        converted["adventure"]["origin_id"] = entry.id
    except (ValueError, TypeError, KeyError, UnicodeDecodeError, CompatibilityError) as exc:
        raise AdventureInstallError(
            "The catalog release is invalid or incompatible: " + str(exc)
        ) from exc
    return {**files, BLUEPRINT_NAME: json.dumps(converted, ensure_ascii=False).encode()}


async def owned_templates(
    db: AsyncSession, owner_id: str, origin_ids: list[str]
) -> list[AdventureTemplate]:
    rows = await db.scalars(
        select(AdventureTemplate).where(
            AdventureTemplate.owner_id == owner_id,
            or_(AdventureTemplate.origin_id.in_(origin_ids), AdventureTemplate.origin_id.is_(None)),
        )
    )
    return [template for template in rows if stable_origin_id(template) in origin_ids]


async def install_entry(
    db: AsyncSession,
    entry: LibraryEntry,
    *,
    owner_id: str,
    http_client: httpx.AsyncClient | None = None,
) -> str:
    """Install a new release alongside older templates; imports never overwrite by title."""
    existing = await owned_templates(db, owner_id, [entry.id])
    latest = max(existing, key=lambda template: version_tuple(template.version or ""), default=None)
    if latest and is_version_at_least(latest.version or "", entry.version):
        return latest.id
    files = convert_files(entry, await fetch_files(entry, http_client))
    data = build_bundle(files)
    imported = await AdventureTemplateImporter.import_adz(
        db,
        data,
        owner_id=owner_id,
        overwrite=False,
        preserve_existing=True,
    )
    if not imported:
        raise AdventureInstallError("The importer rejected this catalog release")
    previous_ids = {template.id for template in existing}
    installed = await owned_templates(db, owner_id, [entry.id])
    template = next(
        (
            template
            for template in installed
            if template.id not in previous_ids and template.version == entry.version
        ),
        None,
    )
    if template is None:
        raise AdventureInstallError(
            "Imported release could not be resolved by its catalog identity"
        )
    return template.id
