"""Shared limits for uploaded visuals and ComfyUI-generated assets."""

# Keep frontend/src/services/visualService.ts upload hints in sync.
VISUAL_LIMITS = {
    "cover": {"maxWidth": 2048, "maxHeight": 1024, "maxBytes": 4 * 1024 * 1024},
    "protagonist": {"maxWidth": 1024, "maxHeight": 1280, "maxBytes": 2 * 1024 * 1024},
    "scene": {"maxWidth": 1600, "maxHeight": 900, "maxBytes": 3 * 1024 * 1024},
    "npc": {"maxWidth": 1024, "maxHeight": 1280, "maxBytes": 2 * 1024 * 1024},
    "object": {"maxWidth": 1024, "maxHeight": 1024, "maxBytes": 2 * 1024 * 1024},
}


def visual_limits(target_type: str | None) -> dict[str, int]:
    kind = (target_type or "object").lower()
    kind = {"character": "npc", "item": "object"}.get(kind, kind)
    return VISUAL_LIMITS.get(kind, VISUAL_LIMITS["object"])
