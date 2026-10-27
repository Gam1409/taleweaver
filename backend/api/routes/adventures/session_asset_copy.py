import logging
import os
import shutil
import uuid

from backend.core.config import settings
from backend.utils.path_security import (
    data_url_to_local_path,
    local_path_to_data_url,
)

logger = logging.getLogger(__name__)


def copy_uncached_session_asset(session_id, bucket, source_url, normalized_source_url, cache):
    from .sessions import (
        _SAFE_IMAGE_EXTENSIONS,
        _ensure_within_data_dir,
        _find_existing_data_asset_path,
        _sanitize_path_component,
    )

    safe_session_id = _sanitize_path_component(session_id)
    safe_bucket = _sanitize_path_component(bucket)
    if not safe_session_id or not safe_bucket:
        logger.warning(
            "Skipping asset copy due to invalid session/bucket: %s / %s", session_id, bucket
        )
        return source_url

    source_path = data_url_to_local_path(normalized_source_url)
    if not source_path:
        logger.warning("Skipping asset copy for unsafe source URL: %s", normalized_source_url)
        return source_url

    if not os.path.isfile(source_path):
        fallback_path = _find_existing_data_asset_path(os.path.basename(source_path))
        if not fallback_path:
            logger.warning(
                "Skipping asset copy because source file does not exist: %s", source_path
            )
            return normalized_source_url
        source_path = fallback_path

    ext = os.path.splitext(source_path)[1].lower()
    if ext not in _SAFE_IMAGE_EXTENSIONS:
        ext = ".png"

    target_dir = _ensure_within_data_dir(
        os.path.join(
            settings.DATA_DIR, "adventures", "sessions", safe_session_id, "visuals", safe_bucket
        )
    )
    os.makedirs(target_dir, exist_ok=True)

    target_name = f"{uuid.uuid4().hex}{ext}"
    target_path = _ensure_within_data_dir(os.path.join(target_dir, target_name))

    try:
        shutil.copy2(source_path, target_path)
    except OSError:
        logger.exception(
            "Failed copying asset to session folder: %s -> %s", source_path, target_path
        )
        return source_url

    from .session_asset_thumbnails import copy_session_asset_thumbnail

    copy_session_asset_thumbnail(source_path, target_path, ext)

    target_url = local_path_to_data_url(target_path)
    cache[normalized_source_url] = target_url
    return target_url
