"""Synchronous ZIP assembly, called from worker threads with detached manifests."""

import io
import json
import os
import zipfile

from fastapi.encoders import jsonable_encoder

from backend.engine.adventure_export_assets import localize_archive_asset
from backend.utils.path_security import ensure_within_data_dir as _ensure_within_data_dir
from backend.utils.path_security import safe_data_path as _safe_data_path


def pack_export_adz(manifest: dict, template_id: str) -> bytes:
    # Gather local assets
    adventure_dir = _safe_data_path("adventures", "library", template_id)
    if not os.path.exists(adventure_dir):
        # Legacy fallback for pre-migration adventures.
        adventure_dir = _safe_data_path("adventures", template_id)
    asset_mapping = {}  # local_path -> zip_path

    def localize_path(path):
        return localize_archive_asset(path, adventure_dir, asset_mapping)

    # Localize all image fields
    manifest["adventure"]["image_url"] = localize_path(manifest["adventure"].get("image_url"))
    if manifest["protagonist"]:
        manifest["protagonist"]["profile_image"] = localize_path(
            manifest["protagonist"].get("profile_image")
        )
    for s in manifest["scenes"]:
        s["image_url"] = localize_path(s.get("image_url"))
    for n in manifest["npcs"]:
        n["image_url"] = localize_path(n.get("image_url"))
    for o in manifest["objects"]:
        o["image_url"] = localize_path(o.get("image_url"))

    # Create the ZIP
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        # 1. Add Manifest
        # Use jsonable_encoder to handle datetime and other non-serializable objects
        encoded_manifest = jsonable_encoder(manifest)
        zip_file.writestr("adventure.adv", json.dumps(encoded_manifest, indent=2))

        # 2. Add Assets
        for local_full, zip_rel in asset_mapping.items():
            if os.path.exists(local_full):
                safe_local_full = _ensure_within_data_dir(local_full)
                zip_file.write(safe_local_full, zip_rel)

    return zip_buffer.getvalue()


def pack_export_ads(manifest: dict, session_id: str) -> bytes:
    # Create the ZIP
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        # 1. Add Manifest
        encoded_manifest = jsonable_encoder(manifest)
        zip_file.writestr("session.json", json.dumps(encoded_manifest, indent=2))

        # 2. Add local assets directory
        session_dir = _safe_data_path("adventures", "sessions", session_id)
        if os.path.exists(session_dir):
            for root, _, files in os.walk(session_dir):
                for file in files:
                    local_full = os.path.join(root, file)
                    safe_local_full = _ensure_within_data_dir(local_full)
                    # Compute relative path within zip
                    rel_path = os.path.relpath(safe_local_full, session_dir)
                    zip_rel = f"assets/{rel_path.replace(os.sep, '/')}"
                    zip_file.write(safe_local_full, zip_rel)

    return zip_buffer.getvalue()
