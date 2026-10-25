"""Manual illustrations for immutable, completed VN story moments."""

from .generation import SceneIllustrationRequest, generate_scene_illustration
from .snapshots import REGISTRY_KEY, capture_scene_snapshot, remap_illustrations

__all__ = [
    "REGISTRY_KEY",
    "SceneIllustrationRequest",
    "capture_scene_snapshot",
    "generate_scene_illustration",
    "remap_illustrations",
]
