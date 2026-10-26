"""Convert supported upstream blueprints to the fork's portable ADV layout."""

from typing import Any

from backend.engine.adventure_compat.common import (
    COLLECTIONS,
    EXTENSIONS,
    CompatibilityError,
    canonical_manifest,
    check_fields,
    check_scripts,
)


def _check_supported_fields(result: dict[str, Any]) -> None:
    allowed = {
        "format",
        "version",
        "adventure",
        "protagonist",
        "init_script",
        "metadata",
        "id",
        *COLLECTIONS,
        *EXTENSIONS,
    }
    if result.keys() - allowed:
        raise CompatibilityError("Unsupported manifest extensions require a reviewed conversion.")
    check_fields(result["adventure"], "adventure")
    check_fields(
        {
            key: value
            for key, value in result.get("protagonist", {}).items()
            if key != "visual_profile"
        },
        "protagonist",
    )
    for kind in COLLECTIONS:
        for record in result[kind]:
            check_fields(
                {
                    key: value
                    for key, value in record.items()
                    if key not in {"visual_profile", "clothing"}
                },
                kind,
            )


def _appearance(record: dict[str, Any]) -> None:
    appearance = record.pop("appearance", None)
    if isinstance(appearance, str) and appearance.strip():
        description = record.get("description") or ""
        record["description"] = f"{description}\nAppearance: {appearance}".strip()


def _interactions(record: dict[str, Any]) -> None:
    metadata = record.get("metadata_json") or {}
    code = record.pop("on_interact_script", None) or metadata.pop("on_interact_script", None)
    text = record.pop("on_interact_text", None) or metadata.pop("on_interact_text", None)
    if not code and not text:
        return
    raise CompatibilityError(
        "Inline interaction hooks require newer upstream interaction semantics."
    )


def import_upstream_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    result = canonical_manifest(manifest, allow_legacy_mode=True)
    _check_supported_fields(result)
    check_scripts(result, inbound=True)
    for sequence in result["sequences"]:
        if sequence.get("soft_rules") or sequence.get("scripts"):
            raise CompatibilityError("Sequence-local rules and scripts require a newer engine.")
        sequence.pop("soft_rules", None)
        sequence.pop("scripts", None)
    _appearance(result.get("protagonist", {}))
    for kind in ("npcs", "objects"):
        for record in result[kind]:
            _appearance(record)
            _interactions(record)
    return result
