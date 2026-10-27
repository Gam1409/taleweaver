import json
import logging
import os
import uuid
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.adventure_format import validate_manifest_version
from backend.core.auth import get_password_hash
from backend.core.config import settings
from backend.models.adventure_template import AdventureTemplate
from backend.models.user import User

logger = logging.getLogger(__name__)

# ZIP-bomb / resource-exhaustion guards for .adz imports.
# Tuned to be permissive enough for legitimate adventures but tight enough
# to stop "decompression bomb" payloads (small archive → huge extracted tree).
MAX_ADZ_TOTAL_ENTRIES = 1000
MAX_ADZ_ENTRY_BYTES = 50 * 1024 * 1024  # 50 MB per file
MAX_ADZ_TOTAL_BYTES = 500 * 1024 * 1024  # 500 MB cumulative
MAX_ADZ_COMPRESSION_RATIO = 100  # uncompressed/compressed size cap


def _ensure_within_data_dir(path: str) -> str:
    data_root = os.path.abspath(settings.DATA_DIR)
    resolved = os.path.abspath(path)
    try:
        if os.path.commonpath([resolved, data_root]) != data_root:
            raise ValueError("Resolved path escapes DATA_DIR.")
    except ValueError as exc:
        raise ValueError("Invalid path: cannot resolve against DATA_DIR.") from exc
    return resolved


# Canonical URLs for well-known license identifiers. Used to auto-fill the
# license_url field during import when a manifest only specifies a short
# license name like "CC BY-NC 4.0" or "MIT".
_LICENSE_URL_DEFAULTS: dict[str, str] = {
    "cc by-nc 4.0": "https://creativecommons.org/licenses/by-nc/4.0/",
    "cc by 4.0": "https://creativecommons.org/licenses/by/4.0/",
    "cc by-sa 4.0": "https://creativecommons.org/licenses/by-sa/4.0/",
    "cc by-nc-sa 4.0": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
    "cc by-nd 4.0": "https://creativecommons.org/licenses/by-nd/4.0/",
    "cc by-nc-nd 4.0": "https://creativecommons.org/licenses/by-nc-nd/4.0/",
    "cc0 1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "mit": "https://opensource.org/licenses/MIT",
    "apache-2.0": "https://www.apache.org/licenses/LICENSE-2.0",
    "apache 2.0": "https://www.apache.org/licenses/LICENSE-2.0",
    "gpl-3.0": "https://www.gnu.org/licenses/gpl-3.0.html",
    "gpl-3.0-or-later": "https://www.gnu.org/licenses/gpl-3.0.html",
    "lgpl-3.0": "https://www.gnu.org/licenses/lgpl-3.0.html",
    "bsd-3-clause": "https://opensource.org/licenses/BSD-3-Clause",
    "bsd-2-clause": "https://opensource.org/licenses/BSD-2-Clause",
    "isc": "https://opensource.org/licenses/ISC",
    "unlicense": "https://unlicense.org/",
    "proprietary": "",
}


def _resolve_license_url(explicit_url: Optional[str], license_name: Optional[str]) -> Optional[str]:
    """Return the license URL, falling back to a known canonical URL for the
    license name if no explicit URL is provided. Returns None when neither is
    available or the license is unknown."""
    if explicit_url:
        return explicit_url
    if not license_name:
        return None
    return _LICENSE_URL_DEFAULTS.get(license_name.strip().lower())


class AdventureConflictError(Exception):
    """Raised when an adventure being imported already exists."""

    def __init__(
        self,
        title: str,
        existing_version: Optional[str],
        new_version: Optional[str],
        template_id: str,
    ):
        self.title = title
        self.existing_version = existing_version
        self.new_version = new_version
        self.template_id = template_id
        super().__init__(f"Adventure '{title}' already exists.")


def _build_local_default_user() -> User:
    # Import-only fallback user; password is intentionally random and unknown.
    return User(
        username="local_default_user",
        hashed_password=get_password_hash(uuid.uuid4().hex),
        role="user",
    )


class AdventureTemplateImporter:
    @staticmethod
    async def import_from_directory(
        db: AsyncSession,
        directory: str,
        owner_id: Optional[str] = None,
        delete_after: bool = False,
        allow_session: bool = False,
        overwrite: bool = False,
    ):
        """Scans a directory for .adv or .adz files and imports them."""
        if not os.path.exists(directory):
            logger.warning(f"Import directory {directory} does not exist.")
            return

        files = [f for f in os.listdir(directory) if f.endswith(".adv") or f.endswith(".adz")]
        if not files:
            return

        logger.info(f"Found {len(files)} potential adventures to import in {directory}")

        for filename in files:
            file_path = os.path.abspath(os.path.join(directory, filename))
            try:
                success = await AdventureTemplateImporter.import_file(
                    db,
                    file_path,
                    owner_id=owner_id,
                    allow_session=allow_session,
                    overwrite=overwrite,
                )
                if success and delete_after:
                    os.remove(file_path)
                    logger.info(f"Successfully imported and deleted {filename}")
                elif success:
                    logger.info(f"Successfully imported {filename}")
            except AdventureConflictError as e:
                logger.warning(f"Skipping '{filename}': already exists (title='{e.title}')")
            except Exception as e:
                logger.error(f"Error during import of {file_path}: {e}")

    @staticmethod
    async def delete_template_for_overwrite(db: AsyncSession, template_id: str):
        """Helper to cleanly delete a template, decoupling sessions and cleaning assets before overwrite import."""
        from backend.api.routes.adventures.logic import AdventureLogic

        await AdventureLogic.delete_adventure(db, template_id)

    @staticmethod
    async def import_file(
        db: AsyncSession,
        file_path: str,
        owner_id: Optional[str] = None,
        allow_session: bool = True,
        overwrite: bool = False,
    ) -> bool:
        """Imports a single file (.adv or .adz)."""
        if file_path.endswith(".adz"):
            with open(file_path, "rb") as f:
                return await AdventureTemplateImporter.import_adz(
                    db, f.read(), owner_id=owner_id, overwrite=overwrite
                )
        elif file_path.endswith(".adv"):
            with open(file_path, encoding="utf-8") as f:
                payload = json.load(f)
                return await AdventureTemplateImporter.import_adv_manifest(
                    db, payload, owner_id=owner_id, allow_session=allow_session, overwrite=overwrite
                )
        return False

    @staticmethod
    async def import_adz(
        db: AsyncSession, adz_data: bytes, owner_id: Optional[str] = None, overwrite: bool = False
    ) -> bool:
        from backend.engine.import_archive import import_adz

        return await import_adz(db, adz_data, owner_id, overwrite)

    @staticmethod
    async def import_adv_manifest(
        db: AsyncSession,
        payload: dict[str, Any],
        owner_id: Optional[str] = None,
        allow_session: bool = True,
        overwrite: bool = False,
    ) -> bool:
        """Logic for pure .adv (JSON) import."""
        try:
            try:
                validate_manifest_version(payload, require_format=True)
            except ValueError as exc:
                logger.error("Invalid ADV format: %s", exc)
                return False

            is_session = payload.get("type") == "SESSION_BUNDLE"
            title = (
                payload.get("adventure", {}).get("title")
                if is_session
                else payload.get("title", "Imported AdventureTemplate")
            )
            origin_id = (
                payload.get("adventure", {}).get("origin_id")
                if is_session
                else payload.get("origin_id")
            )

            query = select(AdventureTemplate).where(
                (AdventureTemplate.owner_id == owner_id)
                if owner_id
                else (AdventureTemplate.owner_id.is_(None))
            )
            if origin_id:
                query = query.where(
                    (AdventureTemplate.title == title) | (AdventureTemplate.origin_id == origin_id)
                )
            else:
                query = query.where(AdventureTemplate.title == title)

            existing_res = await db.execute(query)
            existing = existing_res.scalars().first()
            if existing:
                if not overwrite:
                    raise AdventureConflictError(
                        title=title,
                        existing_version=existing.version,
                        new_version=payload.get("version")
                        or (payload.get("adventure", {}).get("version") if is_session else None),
                        template_id=existing.id,
                    )
                else:
                    logger.info(f"Overwriting existing adventure '{title}'...")
                    await AdventureTemplateImporter.delete_template_for_overwrite(db, existing.id)

            user = None
            if owner_id:
                user_res = await db.execute(select(User).where(User.id == owner_id))
                user = user_res.scalars().first()
            else:
                res = await db.execute(select(User).limit(1))
                user = res.scalars().first()

            if not user:
                user = _build_local_default_user()
                db.add(user)
                await db.flush()

            if is_session and allow_session:
                from backend.engine.import_restore_session_bundle import restore_session_bundle

                return await restore_session_bundle(db, payload, user, origin_id)
            from backend.engine.import_restore_blueprint import restore_blueprint

            return await restore_blueprint(db, payload, user, owner_id, origin_id)
        except AdventureConflictError:
            raise
        except Exception:
            logger.exception("ADV Import failed")
            await db.rollback()
            return False
