"""Bounded ADZ conversion: retain only assets used by the exported blueprint."""

import io
import json
import zipfile
from dataclasses import asdict
from pathlib import PurePosixPath
from typing import Any

from backend.engine.adventure_compat import CompatibilityError, export_upstream_manifest

MAX_BUNDLE_BYTES = 100 * 1024 * 1024
MAX_MANIFEST_BYTES = 5 * 1024 * 1024
MAX_FILES = 2000


class PublicationError(ValueError):
    """The input cannot safely be prepared as a public upstream adventure."""


def _safe_name(name: str) -> bool:
    parts = name.split("/")
    return (
        bool(name)
        and not any(part in {"", ".", ".."} for part in parts)
        and not any(char in name for char in "\\:\x00")
        and (name == "adventure.adv" or (len(parts) > 1 and parts[0] == "assets"))
    )


def _asset_refs(value: Any) -> set[str]:
    if isinstance(value, str):
        if value.startswith("/data/"):
            raise PublicationError(
                "A local asset is missing from the export. Replace it before publishing."
            )
        return {value} if value.startswith("assets/") else set()
    if isinstance(value, dict):
        for key in ("image_url", "profile_image", "cover_url"):
            image = value.get(key)
            if image and (not isinstance(image, str) or not image.startswith("assets/")):
                raise PublicationError(
                    "Publication images must be bundled assets. Upload or remove external images first."
                )
    children = (
        value.values() if isinstance(value, dict) else value if isinstance(value, list) else []
    )
    return set().union(*(_asset_refs(child) for child in children)) if children else set()


def _read_archive(data: bytes) -> tuple[dict, dict[str, bytes]]:
    if len(data) > MAX_BUNDLE_BYTES:
        raise PublicationError("Publication bundle exceeds the 100 MiB limit.")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_FILES or sum(item.file_size for item in infos) > MAX_BUNDLE_BYTES:
            raise PublicationError("Publication archive exceeds its file or size limit.")
        names = [item.filename for item in infos if not item.is_dir()]
        if any(
            item.filename != "assets/" and not _safe_name(item.filename.rstrip("/"))
            for item in infos
            if item.is_dir()
        ):
            raise PublicationError("Publication archive contains unsafe directories.")
        if len(set(names)) != len(names) or any(not _safe_name(name) for name in names):
            raise PublicationError("Publication archive contains duplicate or unsafe paths.")
        if "adventure.adv" not in names:
            raise PublicationError(
                "Expected an ADZ blueprint containing adventure.adv, not a saved session."
            )
        if archive.getinfo("adventure.adv").file_size > MAX_MANIFEST_BYTES:
            raise PublicationError("Adventure manifest is too large.")
        manifest = json.loads(archive.read("adventure.adv"))
        if not isinstance(manifest, dict):
            raise PublicationError("Adventure manifest must be an object.")
        return manifest, {name: archive.read(name) for name in names if name != "adventure.adv"}


def prepare_bundle(data: bytes) -> tuple[bytes, dict]:
    """Return a converted copy and report; caller decides whether to accept changes."""
    try:
        manifest, assets = _read_archive(data)
        converted, report = export_upstream_manifest(manifest)
        references = _asset_refs(converted)
        if any(not _safe_name(name) or name not in assets for name in references):
            raise PublicationError("The adventure references an asset missing from its archive.")
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("adventure.adv", json.dumps(converted, ensure_ascii=False, indent=2))
            for name in sorted(references):
                archive.writestr(str(PurePosixPath(name)), assets[name])
        result = asdict(report)
        result.update(compatible=True, asset_count=len(references))
        result["source_mode"] = (manifest.get("adventure") or {}).get(
            "rule_enforcement_mode", "strict"
        )
        result["target_mode"] = (converted.get("adventure") or {}).get(
            "rule_enforcement_mode", "strict"
        )
        return output.getvalue(), result
    except (RuntimeError, NotImplementedError) as exc:
        raise PublicationError("Encrypted or unsupported archives cannot be published.") from exc
    except (CompatibilityError, zipfile.BadZipFile, UnicodeError, json.JSONDecodeError) as exc:
        raise PublicationError(str(exc)) from exc
