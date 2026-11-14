"""Synchronous ZIP assembly, called from worker threads with detached manifests."""

import io
import json
import os
import zipfile
from contextlib import ExitStack
from dataclasses import dataclass
from typing import BinaryIO

from fastapi.encoders import jsonable_encoder

from backend.engine import archive_safety
from backend.engine.adventure_export_assets import localize_archive_asset
from backend.engine.chpm.notebook_archive import KEY as NOTEBOOK_KEY
from backend.engine.chpm.notebook_archive import NotebookArchive, prepare_notebooks
from backend.engine.export_asset_policy import read_archive_image
from backend.engine.world_info.archive_parts import prepare_world_info
from backend.utils.path_security import ensure_within_data_dir as _ensure_within_data_dir
from backend.utils.path_security import safe_data_path as _safe_data_path


def pack_export_adz(manifest: dict, template_id: str) -> bytes:
    # Gather local assets
    adventure_dir = _safe_data_path("adventures", "library", template_id)
    if not os.path.exists(adventure_dir):
        # Legacy fallback for pre-migration adventures.
        adventure_dir = _safe_data_path("adventures", template_id)
    asset_mapping: dict[str, str] = {}  # local_path -> zip_path

    def localize_path(path: str | None) -> str | None:
        return localize_archive_asset(path, adventure_dir, asset_mapping, template_id=template_id)

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
                zip_file.writestr(zip_rel, read_archive_image(safe_local_full, template_id))

    return zip_buffer.getvalue()


class SessionArchiveLimitError(ValueError):
    """An export cannot be read under the existing portable archive budgets."""


def _session_manifest_bytes(manifest: dict) -> bytes:
    payload = json.dumps(jsonable_encoder(manifest), indent=2).encode("utf-8")
    if len(payload) > archive_safety.MAX_ENTRY_BYTES:
        raise SessionArchiveLimitError("Session manifest exceeds the portable archive size budget.")
    return payload


def _validate_session_stream(output: BinaryIO) -> None:
    try:
        archive_safety.rewind_archive(output)
        with zipfile.ZipFile(output) as archive:
            archive_safety.validate_archive(archive)
    except ValueError:
        raise SessionArchiveLimitError(
            "Session assets exceed the portable archive safety budget."
        ) from None
    output.seek(0)


class _BoundedArchiveOutput:
    """Reject oversized ZIP output while writing, including its final directory."""

    def __init__(self, output: BinaryIO) -> None:
        self.output = output

    def write(self, payload: bytes) -> int:
        if self.output.tell() + len(payload) > archive_safety.MAX_UPLOAD_BYTES:
            raise SessionArchiveLimitError(
                "Session archive exceeds the portable upload size budget."
            )
        return self.output.write(payload)

    def tell(self) -> int:
        return self.output.tell()

    def seek(self, offset: int, whence: int = 0) -> int:
        return self.output.seek(offset, whence)

    def flush(self) -> None:
        self.output.flush()

    def close(self) -> None:
        self.output.close()


@dataclass
class _SessionBudget:
    entries: int = 0
    total: int = 0

    def admit(self, size: int) -> None:
        self.entries += 1
        self.total += size
        if (
            size > archive_safety.MAX_ENTRY_BYTES
            or self.entries > archive_safety.MAX_ENTRIES
            or self.total > archive_safety.MAX_UPLOAD_BYTES
        ):
            raise SessionArchiveLimitError(
                "Session assets exceed the portable archive safety budget."
            )


def _write_session_assets(
    archive: zipfile.ZipFile, session_id: str, budget: _SessionBudget
) -> None:
    session_dir = _safe_data_path("adventures", "sessions", session_id)
    if not os.path.exists(session_dir):
        return
    for root, _, files in os.walk(session_dir):
        for filename in files:
            safe_path = _ensure_within_data_dir(os.path.join(root, filename))
            budget.admit(os.path.getsize(safe_path))
            relative = os.path.relpath(safe_path, session_dir).replace(os.sep, "/")
            archive.write(safe_path, f"assets/{relative}")


def _pack_session_archive(manifest: dict, session_id: str, output: BinaryIO) -> None:
    manifest, world_info_parts = prepare_world_info(manifest)
    manifest, notebook_parts = prepare_notebooks(manifest)
    payload = _session_manifest_bytes(manifest)
    budget = _SessionBudget()
    budget.admit(len(payload))
    output.seek(0)
    output.truncate()
    with zipfile.ZipFile(_BoundedArchiveOutput(output), "w", zipfile.ZIP_DEFLATED) as zip_file:
        # Store source text to preserve the importer's compression-ratio limit.
        zip_file.writestr("session.json", payload, compress_type=zipfile.ZIP_STORED)
        for path, payload in world_info_parts:
            budget.admit(len(payload))
            zip_file.writestr(path, payload, compress_type=zipfile.ZIP_STORED)
        for path, payload in notebook_parts:
            budget.admit(len(payload))
            zip_file.writestr(path, payload, compress_type=zipfile.ZIP_STORED)
        _write_session_assets(zip_file, session_id, budget)
    _validate_session_stream(output)


def pack_export_ads_to(manifest: dict, session_id: str, output: BinaryIO) -> None:
    """Assemble a bounded archive, consuming any detached notebook spool."""
    with ExitStack() as cleanup:
        notebook = manifest.get(NOTEBOOK_KEY)
        if isinstance(notebook, NotebookArchive):
            cleanup.callback(notebook.stream.close)
        _pack_session_archive(manifest, session_id, output)


def pack_export_ads(manifest: dict, session_id: str) -> bytes:
    """Compatibility API for callers that explicitly need an in-memory archive."""
    with io.BytesIO() as output:
        pack_export_ads_to(manifest, session_id, output)
        return output.getvalue()
