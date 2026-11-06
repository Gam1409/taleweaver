import glob
import logging
import os
from typing import Optional

from backend.core.config import settings
from backend.utils.path_security import (
    assert_within_data_dir,
    data_url_to_local_path,
    ensure_within_base_dir,
    local_path_to_data_url,
    safe_data_path,
    sanitize_path_component,
    sanitize_relative_segment,
)

logger = logging.getLogger(__name__)


def resolve_existing_data_asset_url(url: Optional[str]) -> Optional[str]:
    """Best-effort repair for stale /data URLs that no longer match current folders."""
    if not isinstance(url, str):
        return url
    candidate = url.strip()
    if not candidate or not candidate.startswith("/data/"):
        return candidate

    abs_path = data_url_to_local_path(candidate)
    if not abs_path:
        return candidate
    data_root = os.path.abspath(settings.DATA_DIR)
    try:
        if os.path.commonpath([abs_path, data_root]) == data_root and os.path.isfile(abs_path):
            return candidate
    except ValueError:
        return candidate

    filename = os.path.basename(abs_path)
    return _find_relocated_asset(filename, data_root) if filename else candidate


def _find_relocated_asset(filename: str, data_root: str) -> Optional[str]:
    for root in (
        os.path.join(settings.DATA_DIR, "adventures", "library"),
        os.path.join(settings.DATA_DIR, "adventures", "sessions"),
    ):
        root_abs = os.path.abspath(root)
        if not os.path.isdir(root_abs):
            continue
        for alt in glob.iglob(os.path.join(root_abs, "**", filename), recursive=True):
            alt_abs = os.path.abspath(alt)
            try:
                if os.path.commonpath([alt_abs, data_root]) != data_root:
                    continue
            except ValueError:
                continue
            if os.path.isfile(alt_abs):
                rel_alt = os.path.relpath(alt_abs, data_root).replace("\\", "/")
                return f"/data/{rel_alt}"
    # File not found at original location and no replacement found — return None
    # so callers can fall back to alternative image sources rather than serving a 404.
    return None


def _find_protagonist_filename(library_dir: str) -> Optional[str]:
    allowed_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    fuzzy_match = None
    with os.scandir(library_dir) as entries:
        for entry in entries:
            if not entry.is_file() or os.path.splitext(entry.name)[1].lower() not in allowed_exts:
                continue
            name_upper = entry.name.upper()
            if name_upper.startswith("PROTAGONIST."):
                return entry.name
            if "PROTAGONIST" in name_upper and fuzzy_match is None:
                fuzzy_match = entry.name
    return fuzzy_match


def _library_protagonist_url(library_dir: str) -> Optional[str]:
    if not os.path.isdir(library_dir):
        return None
    chosen_name = _find_protagonist_filename(library_dir)
    safe_name = (
        os.path.basename(sanitize_relative_segment(chosen_name) or "") if chosen_name else ""
    )
    if not safe_name:
        return None
    candidate_path = ensure_within_base_dir(os.path.join(library_dir, safe_name), library_dir)
    candidate_path = assert_within_data_dir(candidate_path)
    return local_path_to_data_url(candidate_path) if os.path.isfile(candidate_path) else None


def heal_template_avatar_profile_image(
    template_id: Optional[str], profile_image: Optional[str]
) -> Optional[str]:
    """Repair a deleted session portrait from its original library protagonist image."""
    if not template_id or not profile_image or "/adventures/sessions/" not in profile_image:
        return profile_image
    safe_template_id = sanitize_path_component(template_id)
    if not safe_template_id:
        return profile_image
    abs_path = data_url_to_local_path(profile_image)
    if abs_path and os.path.isfile(abs_path):
        return profile_image
    try:
        library_dir = safe_data_path("adventures", "library", safe_template_id)
        return _library_protagonist_url(library_dir) or profile_image
    except (ValueError, OSError):
        return profile_image
