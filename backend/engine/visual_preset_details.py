"""Owner-facing metadata for the same preset selection used by image generation."""

from typing import Any

from backend.core.comfyui_config import select_profile, select_workflow
from backend.core.image_purposes import image_provider
from backend.engine.comfyui_diagnostics import model_files
from backend.engine.image_profiles import advanced_for
from backend.engine.story_visual_presets import story_t2i
from backend.models.adventure_template import AdventureTemplate


def visual_preset_details(
    settings: dict | None,
    adventure: AdventureTemplate,
    purpose: str,
    advanced: bool | None = None,
    reference: bool = False,
) -> dict[str, Any]:
    try:
        t2i = story_t2i(settings, adventure)
        profile = "advanced" if advanced_for(t2i, purpose, advanced) else "simple"
        provider = image_provider(t2i, profile, purpose)
        details: dict[str, Any] = {"purpose": purpose, "profile": profile, "provider": provider}
        if provider != "comfyui":
            return details
        options = {**t2i, "comfyui_profile": profile, "image_purpose": purpose}
        preset = select_profile(options)
        workflow = select_workflow(options, reference=reference)
        assignments = t2i.get("comfyui_assignments", {})
        return {
            **details,
            "preset_id": assignments.get(purpose) or assignments.get(profile),
            "preset_name": getattr(preset, "name", "Legacy quality profile"),
            "workflow_name": workflow.name,
            "variant": "reference" if reference else "generate",
            "models": model_files(workflow),
        }
    except ValueError:
        # Broken saved choices must not prevent switching back to global settings.
        return {
            "purpose": purpose,
            "error": "The selected image preset is unavailable or incomplete. Choose current global settings or repair the saved preset in Visuals.",
        }
