"""Image intent is independent of output dimensions and legacy quality profiles."""

from typing import Literal

ImagePurpose = Literal[
    "npc", "protagonist", "avatar", "object", "background", "illustration", "cover", "catalog"
]
PresetAssignment = Literal[
    "simple",
    "advanced",
    "npc",
    "protagonist",
    "avatar",
    "object",
    "background",
    "illustration",
    "cover",
    "catalog",
]
PURPOSES = {
    "npc",
    "protagonist",
    "avatar",
    "object",
    "background",
    "illustration",
    "cover",
    "catalog",
}


def purpose_for(kind: str) -> str:
    return {"scene": "background", "item": "object", "character": "npc"}.get(
        kind.lower(), kind.lower()
    )


def image_provider(t2i: dict, profile: str, purpose: str) -> str:
    if (t2i.get("comfyui_assignments") or {}).get(purpose_for(purpose)):
        return "comfyui"
    return str(t2i.get(f"{profile}_model_provider") or t2i.get("provider", "openai")).lower()


def purpose_target(purpose: str) -> str:
    return {
        "background": "scene",
        "illustration": "scene",
        "avatar": "protagonist",
        "catalog": "object",
    }.get(purpose, purpose)
