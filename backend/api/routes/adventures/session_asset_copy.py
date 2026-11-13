import logging
import os
import uuid

from backend.api.routes.adventures.session_asset_access import AssetCopyCache
from backend.core.config import settings
from backend.engine.export_asset_policy import read_bounded_image
from backend.utils.path_security import (
    data_url_to_local_path,
    local_path_to_data_url,
)

logger = logging.getLogger(__name__)


def copy_uncached_session_asset(
    session_id: str,
    bucket: str,
    source_url: str | None,
    normalized_source_url: str,
    cache: dict[str, str],
) -> str | None:
    from .sessions import (
        _ensure_within_data_dir,
        _sanitize_path_component,
    )

    safe_session_id = _sanitize_path_component(session_id)
    safe_bucket = _sanitize_path_component(bucket)
    if not safe_session_id or not safe_bucket:
        logger.warning(
            "Skipping asset copy due to invalid session/bucket: %s / %s", session_id, bucket
        )
        return source_url

    policy = cache if isinstance(cache, AssetCopyCache) else AssetCopyCache()
    try:
        local_path = data_url_to_local_path(normalized_source_url)
        source_path = policy.source_path(local_path) if local_path else None
        data = read_bounded_image(source_path) if source_path else None
    except (ValueError, OSError):
        logger.warning("Skipping session asset: source is not an authorized readable image.")
        return source_url
    if source_path is None or data is None:
        return normalized_source_url

    ext = os.path.splitext(source_path)[1].lower()

    target_dir = _ensure_within_data_dir(
        os.path.join(
            settings.DATA_DIR, "adventures", "sessions", safe_session_id, "visuals", safe_bucket
        )
    )
    os.makedirs(target_dir, exist_ok=True)

    target_name = f"{uuid.uuid4().hex}{ext}"
    target_path = _ensure_within_data_dir(os.path.join(target_dir, target_name))

    try:
        with open(target_path, "wb") as target:
            target.write(data)
    except OSError:
        logger.exception(
            "Failed copying asset to session folder: %s -> %s", source_path, target_path
        )
        return source_url

    from .session_asset_thumbnails import create_session_asset_thumbnail

    create_session_asset_thumbnail(target_path, ext)

    target_url = local_path_to_data_url(target_path)
    cache[normalized_source_url] = target_url
    return target_url
