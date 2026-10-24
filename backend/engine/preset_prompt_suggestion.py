"""Use the actual selected image preset for the editor's Suggest Prompt action."""

from fastapi import HTTPException

from backend.core import prompts
from backend.core.comfyui_config import prompt_rules
from backend.core.llm_router import GameMasterLLM
from backend.core.style_catalog import resolve_style_instruction, resolve_tone_instruction
from backend.engine.image_profiles import advanced_for
from backend.engine.image_prompt_adapter import adapt_body
from backend.engine.story_visual_presets import story_t2i


async def suggest_image_prompt(user, adventure, payload, name: str, description: str) -> str:
    suggested = await suggest_preset_prompt(user, adventure, payload, name, description)
    if suggested is not None:
        return suggested
    llm = GameMasterLLM.for_role(user, "small")
    user_prompt = prompts.IMAGE_PROMPT_SUGGESTION_USER_PROMPT_TEMPLATE.format(
        target_type=payload.target_type.upper(), name=name, description=description
    )
    suggested = await llm.aexecute_simple_task(
        system_prompt=prompts.IMAGE_PROMPT_SUGGESTION_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        model=llm.model,
    )
    return suggested.strip()


async def suggest_preset_prompt(
    user, adventure, payload, name: str, description: str
) -> str | None:
    try:
        t2i = story_t2i(user.t2i_settings, adventure)
        profile = (
            "advanced"
            if advanced_for(t2i, payload.target_type, payload.use_advanced_model)
            else "simple"
        )
        if t2i.get(f"{profile}_model_provider") != "comfyui":
            return None
        rules = prompt_rules({**t2i, "comfyui_profile": profile})
        if not rules:
            return None
        style = resolve_style_instruction(
            adventure.selected_image_styles, user.image_styles_catalog
        )
        tone = resolve_tone_instruction(adventure.selected_tone, user.tone_catalog)
        source = f"Asset: {payload.target_type}. Name: {name}. Description: {description}. Style: {style}. Mood: {tone}."
        # Return the editable body. Mandatory prefix/suffix are added only at generation.
        return await adapt_body(source, rules, user)
    except Exception as exc:
        raise HTTPException(
            400,
            "Could not adapt the prompt. Check the story preset and Small/Utility LLM settings.",
        ) from exc
