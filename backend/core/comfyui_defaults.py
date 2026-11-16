"""Editable standard presets with pinned workflows, independent of server connectivity."""

from copy import deepcopy
from functools import lru_cache
from itertools import product
from typing import get_args

from backend.core.comfyui_task_templates import task_preset
from backend.core.image_purposes import ImagePurpose

STANDARD_FAMILIES = ("anima", "illustrious")


@lru_cache(maxsize=1)
def _bundle() -> dict:
    presets = {}
    workflows = {}
    for family, purpose in product(STANDARD_FAMILIES, get_args(ImagePurpose)):
        identifier = f"standard-{family}-{purpose}"
        preset = task_preset(family, purpose)["preset"]
        presets[identifier] = preset
        workflows.update(
            {
                f"{identifier}-{variant}": {"revision": 1, "workflow": deepcopy(preset[variant])}
                for variant in ("generate", "reference")
                if preset[variant] is not None
            }
        )
    return {"comfyui_presets": presets, "comfyui_workflows": workflows}


def standard_presets() -> dict:
    """Return independent copies; caller edits must never alter the bundled originals."""
    return deepcopy(_bundle())
