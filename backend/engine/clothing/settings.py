"""Author-owned clothing detail preferences, never controlled by model output."""

from typing import Any

MANIFEST_KEY = "clothing_settings"


def clothing_settings(manifest: Any) -> dict[str, bool]:
    raw = manifest.get(MANIFEST_KEY) if isinstance(manifest, dict) else None
    return {"detailed": isinstance(raw, dict) and raw.get("detailed") is True}


def with_clothing_settings(manifest: Any, detailed: bool) -> dict:
    return {
        **(manifest if isinstance(manifest, dict) else {}),
        MANIFEST_KEY: {"detailed": detailed is True},
    }


def preserve_clothing_settings(manifest: dict, adventure: Any) -> dict:
    return {
        **manifest,
        MANIFEST_KEY: clothing_settings(getattr(adventure, "original_manifest", None)),
    }
