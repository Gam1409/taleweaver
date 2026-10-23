"""Lossless upgrade of the original two workflow slots into named presets."""

import copy


def normalize_comfy_presets(data: dict) -> dict:
    result = dict(data)
    presets = copy.deepcopy(data.get("comfyui_presets") or {})
    assignments = dict(data.get("comfyui_assignments") or {})
    for role, profile in (data.get("comfyui_profiles") or {}).items():
        if (
            role in assignments
            or not profile
            or not (profile.get("generate") or profile.get("reference"))
        ):
            continue
        key = f"legacy-{role}"
        while key in presets:
            key += "-copy"
        presets[key] = {
            **copy.deepcopy(profile),
            "name": f"Existing {role} workflow",
            "prompt_rules": None,
            "auto_prompt_template": False,
        }
        assignments[role] = key
    result["comfyui_presets"] = presets
    result["comfyui_assignments"] = assignments
    return result
