"""Legacy visual prompt composition, independent of HTTP routes."""

from typing import Any, Optional

from fastapi import HTTPException


def build_visual_prompt(
    target_type: str,
    target_obj: Any,
    custom_prompt: Optional[str],
    *,
    style_instruction: Optional[str] = None,
    tone_instruction: Optional[str] = None,
) -> str:
    if custom_prompt and custom_prompt.strip():
        return custom_prompt.strip()

    prompt_suffix = ""
    if style_instruction:
        prompt_suffix += f" Style constraints: {style_instruction}."
    if tone_instruction:
        prompt_suffix += f" Narrative tone reference: {tone_instruction}."

    def get_attr(obj: Any, attr: str, default: str = "") -> Any:
        if isinstance(obj, dict):
            return obj.get(attr) or default
        return getattr(obj, attr, None) or default

    if target_type == "protagonist":
        name = get_attr(target_obj, "name", "The protagonist")
        role = get_attr(target_obj, "role", "adventurer")
        description = get_attr(target_obj, "description", "A distinctive fantasy hero.")
        return f"Portrait of character {name}, {role}. {description}. Game character art style.{prompt_suffix}"

    if target_type == "scene":
        label = get_attr(target_obj, "label") or get_attr(target_obj, "name") or "Scene"
        description = get_attr(target_obj, "description")
        return f"Atmospheric background: {label}. {description}. RPG visual novel style, high detail.{prompt_suffix}"

    if target_type == "npc":
        name = get_attr(target_obj, "name", "NPC")
        description = get_attr(target_obj, "description", "A distinctive non-player character.")
        return f"Portrait of NPC {name}. {description}. Character portrait, high detail.{prompt_suffix}"

    if target_type == "object":
        name = get_attr(target_obj, "name", "Object")
        description = get_attr(target_obj, "description", "A detailed fantasy object.")
        return f"Detailed illustration of object {name}. {description}. Fantasy item concept art, isolated and clearly readable.{prompt_suffix}"

    raise HTTPException(status_code=400, detail="Unsupported visual target type.")
