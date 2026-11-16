"""Keep image-copy permissions with the operation's existing URL cache."""

import os
from collections.abc import Iterable, Iterator
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.engine.export_asset_policy import IMAGE_EXTENSIONS, SHARED_IMAGE_ROOTS
from backend.models.adventure_template import AdventureTemplate
from backend.models.game_session import GameSession
from backend.models.user import User
from backend.utils.path_security import (
    ensure_within_data_dir,
    safe_data_path,
    sanitize_path_component,
)


class AssetCopyCache(dict[str, str]):
    """An operation-local cache with explicit authorized source owners."""

    def __init__(
        self, *, session_ids: Iterable[str] = (), template_ids: Iterable[str] = ()
    ) -> None:
        super().__init__()
        self.session_ids = frozenset(session_ids)
        self.template_ids = frozenset(template_ids)

    def checked_source(self, path: str) -> str:
        canonical = ensure_within_data_dir(path)
        relative = Path(canonical).relative_to(Path(settings.DATA_DIR).resolve())
        if relative.suffix.lower() not in IMAGE_EXTENSIONS or not self._allows(relative.parts):
            raise ValueError("Image source is not authorized for this copy.")
        return canonical

    def _allows(self, parts: tuple[str, ...]) -> bool:
        if not parts:
            return False
        if len(parts) == 1 or parts[0] in SHARED_IMAGE_ROOTS:
            return True
        if len(parts) < 3 or parts[0] != "adventures":
            return False
        if parts[1] == "sessions":
            return len(parts) >= 4 and parts[2] in self.session_ids
        if parts[1] == "library":
            return len(parts) >= 4 and parts[2] in self.template_ids
        return parts[1] in self.template_ids

    def source_path(self, path: str) -> str | None:
        """Recover legacy filenames only after authorizing the requested scope."""
        canonical = self.checked_source(path)
        if os.path.isfile(canonical):
            return canonical
        filename = Path(canonical).name
        for candidate in self._fallback_candidates(filename):
            try:
                authorized = self.checked_source(str(candidate))
            except ValueError:
                continue
            if os.path.isfile(authorized):
                return authorized
        return None

    def _fallback_candidates(self, filename: str) -> Iterator[Path]:
        yield from Path(settings.DATA_DIR).glob(filename)
        roots: list[tuple[str, ...]] = [(name,) for name in sorted(SHARED_IMAGE_ROOTS)]
        roots.extend(("adventures", "sessions", key) for key in sorted(self.session_ids))
        roots.extend(("adventures", "library", key) for key in sorted(self.template_ids))
        roots.extend(
            ("adventures", key)
            for key in sorted(self.template_ids)
            if key not in {"library", "sessions"}
        )
        for parts in roots:
            root = _existing_root(parts)
            if root is not None:
                yield from root.rglob(filename)


def _existing_root(parts: tuple[str, ...]) -> Path | None:
    if any(sanitize_path_component(part) is None for part in parts):
        return None
    try:
        root = Path(safe_data_path(*parts))
    except ValueError:
        return None
    return root if root.is_dir() else None


async def build_asset_copy_cache(db: AsyncSession, user_id: str | None) -> AssetCopyCache:
    """Load owned sessions and visible templates once for this copy operation."""
    user = await db.get(User, user_id) if user_id else None
    if user is None:
        return AssetCopyCache()
    sessions = select(GameSession.id)
    templates = select(AdventureTemplate.id)
    if user.role != "admin":
        sessions = sessions.where(GameSession.user_id == user.id)
        templates = templates.where(
            AdventureTemplate.owner_id.is_(None) | (AdventureTemplate.owner_id == user.id)
        )
    return AssetCopyCache(
        session_ids=(await db.scalars(sessions)).all(),
        template_ids=(await db.scalars(templates)).all(),
    )
