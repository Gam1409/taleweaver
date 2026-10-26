"""Pure, conservative boundaries for portable adventure manifests."""

import ast
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from backend.core.adventure_format import validate_manifest_version
from backend.engine.adventure_compat.fields import FIELDS


class CompatibilityError(ValueError):
    """The adventure cannot be converted without losing unsupported behavior."""


@dataclass
class ConversionReport:
    warnings: list[str] = field(default_factory=list)
    requires_acknowledgement: bool = False
    source_format: str = "fork"
    target_format: str = "upstream-2e042ef2"

    def warn(self, message: str, *, acknowledge: bool = False) -> None:
        if message not in self.warnings:
            self.warnings.append(message)
        self.requires_acknowledgement |= acknowledge


COLLECTIONS = ("scenes", "exits", "npcs", "objects", "quests", "awards", "sequences", "scripts")
EXTENSIONS = frozenset({"visual_presets", "npc_card_settings", "clothing_settings"})


def _validate_envelope(manifest: dict[str, Any]) -> None:
    if not isinstance(manifest, dict):
        raise CompatibilityError("An adventure manifest must be a JSON object.")
    if any(key in manifest for key in ("session", "session_state", "chat_messages", "messages")):
        raise CompatibilityError("Saved sessions cannot be published or installed as adventures.")
    try:
        version = validate_manifest_version(manifest)
    except ValueError as exc:
        raise CompatibilityError(str(exc)) from exc
    numbers = tuple(int(part) for part in version.split("."))
    if numbers > (1, 3):
        raise CompatibilityError("This converter supports adventure formats 1.0 through 1.3.")


def _normalize_metadata(result: dict[str, Any], *, allow_legacy_mode: bool) -> None:
    meta = result.get("adventure", {})
    if not isinstance(meta, dict):
        raise CompatibilityError("Adventure metadata must be an object.")
    for key in FIELDS["adventure"] - {"version", "init_script"}:
        if key in result:
            meta.setdefault(key, result.pop(key))
    result["adventure"] = meta
    result["format"] = "TaleWeaver"
    if "init_script" in meta:
        if result.get("init_script") and result["init_script"] != meta["init_script"]:
            raise CompatibilityError("Conflicting initialization scripts require manual review.")
        result["init_script"] = meta.pop("init_script")
    if not isinstance(meta.get("title"), str) or not meta["title"].strip():
        raise CompatibilityError("Adventure title is required.")
    mode = meta.get("rule_enforcement_mode", "rpg")
    allowed_modes = {"rpg", "story", "chat", "vn"}
    if allow_legacy_mode:
        allowed_modes.add("strict")
    if mode not in allowed_modes:
        raise CompatibilityError(
            "Choose RPG, Story or Chat in adventure settings before publishing this legacy mode."
        )


def canonical_manifest(
    manifest: dict[str, Any], *, allow_legacy_mode: bool = False
) -> dict[str, Any]:
    """Normalize the two real ADV layouts without reserializing away extra data."""
    _validate_envelope(manifest)
    result = deepcopy(manifest)
    _normalize_metadata(result, allow_legacy_mode=allow_legacy_mode)
    if not isinstance(result.get("protagonist", {}), dict):
        raise CompatibilityError("Protagonist must be an object.")
    for key in COLLECTIONS:
        records = result.get(key, [])
        if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
            raise CompatibilityError(f"{key} must be a list of objects.")
        result[key] = records
    _validate_containers(result)
    return result


def _validate_containers(result: dict[str, Any]) -> None:
    records = [
        result["adventure"],
        result.get("protagonist", {}),
        *result["npcs"],
        *result["objects"],
    ]
    for record in records:
        for key in ("metadata_json", "stats", "visual_profile", "clothing", "time_config"):
            if record.get(key) is not None and not isinstance(record[key], dict):
                raise CompatibilityError(f"{key} must be an object.")
        profile = record.get("visual_profile") or {}
        if profile.get("appearance") is not None and not isinstance(profile["appearance"], dict):
            raise CompatibilityError("Visual appearance must be an object.")


def check_fields(record: dict[str, Any], kind: str) -> None:
    unknown = record.keys() - FIELDS[kind]
    if unknown:
        raise CompatibilityError(
            f"Unsupported {kind} fields; conversion would lose custom behavior."
        )


def script_sources(value: Any, key: str = "") -> list[str]:
    if isinstance(value, dict):
        return [code for name, item in value.items() for code in script_sources(item, name)]
    if isinstance(value, list):
        return [code for item in value for code in script_sources(item, key)]
    if isinstance(value, str) and (
        key.endswith(("_script", "_expression")) or key in {"code", "script"}
    ):
        return [value] if value.strip() else []
    return []


def check_scripts(manifest: dict[str, Any], *, inbound: bool) -> None:
    """Reject known incompatible APIs, including aliases resolved by Python attributes."""
    forbidden = (
        {"dialog", "give_to_player"} if inbound else {"clothing", "wardrobe", "visual_profile"}
    )
    for code in script_sources(manifest):
        try:
            nodes = ast.walk(ast.parse(code))
        except SyntaxError as exc:
            raise CompatibilityError("An adventure script has invalid Python syntax.") from exc
        if any(isinstance(node, ast.Attribute) and node.attr in forbidden for node in nodes):
            raise CompatibilityError(
                "An adventure script uses an API unavailable in the target edition."
            )
