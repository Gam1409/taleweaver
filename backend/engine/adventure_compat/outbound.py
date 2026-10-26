"""Export a public upstream blueprint with explicit reports for lossy conversions."""

import ast
from typing import Any

from backend.engine.adventure_compat.common import (
    COLLECTIONS,
    EXTENSIONS,
    CompatibilityError,
    ConversionReport,
    canonical_manifest,
    check_fields,
    check_scripts,
    script_sources,
)
from backend.engine.adventure_compat.privacy import public_content


def _require_publication_metadata(meta: dict[str, Any]) -> None:
    version = meta.get("version")
    if not isinstance(version, str) or not version.strip():
        raise CompatibilityError(
            "Set an adventure release version before publishing; the file format version is not a release version."
        )
    origin_id = meta.get("origin_id")
    if not isinstance(origin_id, str) or not origin_id.strip():
        raise CompatibilityError(
            "This archive has no stable origin ID. Export it again from TaleWeaver before publishing."
        )


def _visuals(record: dict[str, Any], report: ConversionReport) -> None:
    profile = record.pop("visual_profile", None)
    if isinstance(profile, dict):
        appearance = profile.get("appearance") or {}
        fragments = [
            str(appearance[key])
            for key in ("hair", "eyes", "build", "features")
            if appearance.get(key)
        ]
        if appearance.get("age_years") is not None:
            fragments.insert(0, f"age {appearance['age_years']}")
        if fragments:
            record["appearance"] = ", ".join(filter(None, [record.get("appearance"), *fragments]))
        report.warn(
            "Detailed appearance and worn layers become descriptive appearance; clothing behavior is unavailable upstream.",
            acknowledge=True,
        )
    garment = record.pop("clothing", None)
    metadata = record.get("metadata_json")
    if isinstance(metadata, dict):
        garment = metadata.pop("clothing", None) or garment
    if garment:
        report.warn(
            "Clothing layers are omitted; the original items and ownership are preserved.",
            acknowledge=True,
        )


def export_upstream_manifest(manifest: dict[str, Any]) -> tuple[dict[str, Any], ConversionReport]:
    report = ConversionReport()
    result = canonical_manifest(manifest)
    _require_publication_metadata(result["adventure"])
    check_scripts(result, inbound=False)
    script_names = frozenset(
        node.value
        for source in script_sources(result)
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    )
    result = public_content(result, report, script_names)
    for extension in EXTENSIONS:
        value = result.pop(extension, None)
        if value:
            report.warn(
                f"Fork-specific {extension.replace('_', ' ')} are unavailable upstream.",
                acknowledge=True,
            )
    meta = result["adventure"]
    if meta.get("rule_enforcement_mode") == "vn":
        meta.update(rule_enforcement_mode="chat", strict_rules=False)
        report.warn(
            "Visual Novel mode becomes Chat/History. VN pacing, social reasoning and continuity rules are not supported upstream.",
            acknowledge=True,
        )
    check_fields(meta, "adventure")
    allowed = {
        "format",
        "version",
        "adventure",
        "protagonist",
        "init_script",
        "metadata",
        *COLLECTIONS,
    }
    if result.keys() - allowed:
        raise CompatibilityError("Unsupported manifest extensions require a reviewed conversion.")
    if "protagonist" in result:
        _visuals(result["protagonist"], report)
        check_fields(result["protagonist"], "protagonist")
    for kind in COLLECTIONS:
        for record in result[kind]:
            _visuals(record, report)
            check_fields(record, kind)
    return result, report
