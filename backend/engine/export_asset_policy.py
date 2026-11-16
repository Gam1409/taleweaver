"""Read only bounded images from this adventure or explicitly shared media roots."""

import io
import os
from pathlib import Path
from xml.etree.ElementTree import ParseError

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from PIL import Image

from backend.core.config import settings
from backend.engine.archive_safety import MAX_ENTRY_BYTES
from backend.utils.path_security import ensure_within_data_dir

IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif", ".ico", ".svg"})
# These legacy media roots are also readable by authenticated users through
# authorize_media(). Private adventures/sessions are deliberately excluded.
SHARED_IMAGE_ROOTS = frozenset({"catalog", "characters", "users", "placeholders"})
ERROR = "Archive image reference is not an authorized readable image."


def checked_asset_path(path: str, template_id: str) -> str:
    canonical = ensure_within_data_dir(path)
    parts = Path(os.path.relpath(canonical, os.path.realpath(settings.DATA_DIR))).parts
    scoped = parts[:3] == ("adventures", "library", template_id)
    legacy = template_id not in {"library", "sessions"} and parts[:2] == ("adventures", template_id)
    shared = len(parts) == 1 or (bool(parts) and parts[0] in SHARED_IMAGE_ROOTS)
    if Path(canonical).suffix.lower() not in IMAGE_EXTENSIONS or not (scoped or legacy or shared):
        raise ValueError(ERROR)
    return canonical


def read_archive_image(path: str, template_id: str) -> bytes:
    """Validate the exact bytes subsequently written to ZIP, without reopening them."""
    return read_bounded_image(checked_asset_path(path, template_id))


def read_bounded_image(path: str) -> bytes:
    """Validate bounded image bytes after the caller has authorized their source scope."""
    canonical = ensure_within_data_dir(path)
    try:
        if not Path(canonical).is_file():
            raise ValueError(ERROR)
        with open(canonical, "rb") as source:
            data = source.read(MAX_ENTRY_BYTES + 1)
    except OSError as exc:
        raise ValueError(ERROR) from exc
    if len(data) > MAX_ENTRY_BYTES:
        raise ValueError("Archive image exceeds the asset size budget.")
    try:
        if Path(canonical).suffix.lower() == ".svg" or data.lstrip().startswith(b"<"):
            _verify_svg(data)
        else:
            with Image.open(
                io.BytesIO(data), formats=["PNG", "JPEG", "WEBP", "GIF", "AVIF", "ICO"]
            ) as image:
                image.verify()
    except (
        OSError,
        ValueError,
        SyntaxError,
        ParseError,
        DefusedXmlException,
        Image.DecompressionBombError,
    ) as exc:
        raise ValueError(ERROR) from exc
    return data


def _verify_svg(data: bytes) -> None:
    if len(data) > 1024 * 1024:
        raise ValueError(ERROR)
    root = ElementTree.fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    if root.tag.rsplit("}", 1)[-1] != "svg":
        raise ValueError(ERROR)
