"""Author-owned NSFW narration preferences, never controlled by model output."""

from typing import Any

MANIFEST_KEY = "nsfw_settings"

NSFW_LEVELS = ("soft", "medium", "hard")


def normalize_nsfw_level(level: Any) -> str:
    value = str(level or "").strip().lower()
    return value if value in NSFW_LEVELS else "soft"


def nsfw_settings(manifest: Any) -> dict[str, Any]:
    raw = manifest.get(MANIFEST_KEY) if isinstance(manifest, dict) else None
    enabled = isinstance(raw, dict) and raw.get("enabled") is True
    level = raw.get("level") if isinstance(raw, dict) else None
    return {"enabled": enabled, "level": normalize_nsfw_level(level)}


def with_nsfw_settings(manifest: Any, enabled: bool, level: str) -> dict:
    return {
        **(manifest if isinstance(manifest, dict) else {}),
        MANIFEST_KEY: {"enabled": enabled is True, "level": normalize_nsfw_level(level)},
    }


def preserve_nsfw_settings(manifest: dict, adventure: Any) -> dict:
    return {
        **manifest,
        MANIFEST_KEY: nsfw_settings(getattr(adventure, "original_manifest", None)),
    }
