"""File-only upload persistence; database updates stay in the request task."""

import os
import shutil
from typing import BinaryIO
from uuid import uuid4

from backend.core.config import settings
from backend.utils.path_security import (
    ensure_within_base_dir,
    local_path_to_data_url,
    safe_data_path,
)


def save_catalog_image(
    catalog_type: str, target_id: str, content_type: str | None, content: bytes
) -> dict[str, str]:
    from backend.api.routes.config_api import (
        _build_catalog_upload_path,
        _ensure_within_data_dir,
        _extension_from_content_type,
    )

    safe_ext = _extension_from_content_type(content_type)
    filepath = _build_catalog_upload_path(catalog_type, target_id, f"upload.{safe_ext}")
    safe_filepath = _ensure_within_data_dir(filepath)
    safe_parent_dir = _ensure_within_data_dir(os.path.dirname(safe_filepath))
    safe_filepath = ensure_within_base_dir(safe_filepath, safe_parent_dir)
    # Re-verify containment at the sink so the taint analysis trusts the path.
    data_root = os.path.realpath(settings.DATA_DIR)
    if os.path.commonpath([os.path.realpath(safe_filepath), data_root]) != data_root:
        raise ValueError("Invalid filepath: escapes DATA_DIR.")
    with open(safe_filepath, "wb") as f:
        f.write(content)
    rel_path = os.path.relpath(safe_filepath, settings.DATA_DIR).replace("\\", "/")
    return {"status": "success", "image_url": f"/data/{rel_path}"}


def save_profile_image(safe_user_id: str, original_filename: str | None, source: BinaryIO) -> str:
    from backend.api.routes.users_api import _ensure_within_data_dir, _sanitize_image_extension

    upload_dir = safe_data_path("users")
    os.makedirs(upload_dir, exist_ok=True)

    file_ext = _sanitize_image_extension(original_filename)
    filename = f"{safe_user_id}_{uuid4().hex[:8]}{file_ext}"
    file_path = _ensure_within_data_dir(os.path.join(upload_dir, filename))

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(source, buffer)

    return local_path_to_data_url(file_path)
