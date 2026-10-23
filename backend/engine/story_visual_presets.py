"""Story choices reference administrator presets, never embedded server workflows."""

from backend.core.comfyui_config import ComfySettings, select_workflow
from backend.core.comfyui_presets import normalize_comfy_presets


def preserve_story_presets(manifest: dict, adventure) -> dict:
    original = getattr(adventure, "original_manifest", None) or {}
    if "visual_presets" not in original:
        return dict(manifest)
    return {**manifest, "visual_presets": dict(story_selection(adventure))}


def story_selection(adventure) -> dict[str, str]:
    manifest = getattr(adventure, "original_manifest", None) or {}
    selection = manifest.get("visual_presets", {})
    if not isinstance(selection, dict):
        raise ValueError("Invalid story visual preset selection.")
    if any(k not in ("simple", "advanced") or not isinstance(v, str) for k, v in selection.items()):
        raise ValueError("Invalid story visual preset selection.")
    return selection


def story_t2i(t2i: dict | None, adventure) -> dict:
    result = normalize_comfy_presets(t2i or {})
    selection = story_selection(adventure)
    if not selection:
        return result
    presets = ComfySettings.model_validate(result).comfyui_presets
    for profile, preset_id in selection.items():
        if preset_id not in presets:
            raise ValueError(
                "A story image preset is unavailable. Re-select it in the story's Visuals settings."
            )
        result[f"{profile}_model_provider"] = "comfyui"
    result["comfyui_assignments"] = {**result.get("comfyui_assignments", {}), **selection}
    for profile in selection:
        select_workflow({**result, "comfyui_profile": profile})
    return result
