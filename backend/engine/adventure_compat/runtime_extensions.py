"""Portable namespaces stay opaque; upstream preparation reports runtime degradation."""

from copy import deepcopy

from backend.engine.adventure_compat.common import CompatibilityError, ConversionReport
from backend.engine.agent_runtime_contract import inspect_runtime


def runtime_blocks(manifest: dict) -> list:
    return [
        manifest.get("extensions", {}),
        *[
            (npc.get("metadata_json") or {}).get("agent_runtime")
            for npc in manifest.get("npcs", [])
        ],
    ]


def check_public_extensions(before: dict, after: dict, report: ConversionReport) -> None:
    if runtime_blocks(before) != runtime_blocks(after):
        raise CompatibilityError(
            "Extension fields excluded from publication require manual review."
        )
    raw = (after.get("extensions") or {}).get("agent_runtime")
    if raw is None:
        return
    result = inspect_runtime(raw)
    if result.status not in {"ready", "missing_required"} or raw.get("fallback", "core") == "block":
        raise CompatibilityError("This agent runtime cannot fall back to original TaleWeaver.")
    report.warn(
        "Original TaleWeaver preserves agent_runtime but does not execute autonomous NPC, psychology, RAG or Living World settings. Core fallback applies.",
        acknowledge=True,
    )


def omit_local_options(result: dict, report: ConversionReport) -> dict:
    """Only known local export fields are removed, with explicit conversion warnings."""
    result = deepcopy(result)
    for key in ("living_world_settings", "npc_personality_settings"):
        if result["adventure"].pop(key, None):
            report.warn(f"Local {key} are unavailable upstream.", acknowledge=True)
    result.pop("visual_preset_source", None)
    for key in ("narrator_settings", "world_brief", "world_brief_sources"):
        if result.pop(key, None):
            report.warn(f"Local {key} are omitted from this compatible copy.", acknowledge=True)
    return result
