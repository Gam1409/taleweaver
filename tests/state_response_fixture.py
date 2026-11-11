"""Explicit unchanged sections for provider doubles that model complete state responses."""

from typing import Any, TypeVar

from backend.engine.narrated_items.schema import ItemExtraction

T = TypeVar("T", bound=ItemExtraction)


def extraction(model: type[T], **changes: Any) -> T:
    return model.model_validate(
        {
            "actions": [],
            "condition_updates": [],
            "scene_updates": [],
            "final_frame_actions": [],
            "movements": [],
            **changes,
        }
    )
