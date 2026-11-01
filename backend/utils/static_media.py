"""Serve passive media with filesystem probes off the event loop."""

import logging
import re
import stat
from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles

from backend.engine.archive_safety import MEDIA_EXTENSIONS
from backend.utils.async_files import run_file_operation

logger = logging.getLogger(__name__)


def _is_svg(path):
    try:
        with open(path, "rb") as source:
            return b"<svg" in source.read(512).lower()
    except OSError:
        return False


class SafeStaticFiles(StaticFiles):
    """Serve passive media only; runtime state and executable assets remain private."""

    async def _ensure_thumbnail(self, path):
        match = re.match(r"^(.*)_thumb(\.[a-zA-Z0-9]+)$", path, re.IGNORECASE)
        if not match:
            return
        source_path, source_stat = await run_file_operation(
            self.lookup_path, f"{match.group(1)}{match.group(2)}"
        )
        if source_stat is None or not stat.S_ISREG(source_stat.st_mode):
            return
        from backend.engine.media_engine import MediaEngine

        try:
            await MediaEngine._generate_thumbnail(source_path)
        except Exception:
            logger.exception("Dynamic thumbnail generation failed for %s", source_path)

    async def get_response(self, path, scope):
        if Path(path).suffix.lower() not in MEDIA_EXTENSIONS:
            raise HTTPException(status_code=403, detail="Access denied")
        full_path, stat_result = await run_file_operation(self.lookup_path, path)
        if stat_result is None:
            await self._ensure_thumbnail(path)
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            full_path, stat_result = await run_file_operation(self.lookup_path, path)
            if (
                stat_result is not None
                and stat.S_ISREG(stat_result.st_mode)
                and await run_file_operation(_is_svg, full_path)
            ):
                response.headers["Content-Type"] = "image/svg+xml"
        response.headers["Content-Security-Policy"] = (
            "sandbox; default-src 'none'; style-src 'unsafe-inline'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
