"""Build a moment illustration using the story's existing image provider and style."""

from uuid import uuid4

from backend.core.comfyui_config import prompt_rules, select_profile
from backend.core.image_prompt_rules import ImagePromptRules
from backend.engine.image_profiles import advanced_for
from backend.engine.image_prompt_adapter import adapt_body
from backend.engine.media_engine import MediaEngine
from backend.engine.session_portraits import _settings
from backend.utils.path_security import safe_data_path

from . import source_quality
from .visual_context import VisualContext


async def image_request(db, state, user, snapshot: dict) -> tuple[dict, dict]:
    t2i, style, tone = await _settings(db, state, user, kind="scene")
    profile = "advanced" if advanced_for(t2i, "scene") else "simple"
    provider = (t2i.get(f"{profile}_model_provider") or t2i.get("provider", "openai")).lower()
    options = {
        **t2i,
        "visual_target_type": "scene",
        "comfyui_profile": profile,
        "_prompt_user": user,
        "_prompt_prepared": False,
        **{
            key: t2i.get(f"{profile}_{key}")
            for key in ("steps", "cfg_scale", "sampler_name", "scheduler")
        },
    }
    if provider in ("stable_diffusion", "ollama", "comfyui"):
        width, height = MediaEngine._resolve_sd_dimensions(
            "SCENE", t2i.get(f"{profile}_min_long_edge")
        )
        options.update(width=width, height=height)
    selected_snapshot = {
        **snapshot,
        "narration": snapshot.get("full_narration", snapshot["narration"]),
    }
    context = VisualContext.from_snapshot(selected_snapshot, tone)
    prompt = source_quality.build_prompt(context, style)
    ext = "jpg" if (t2i.get("image_format") or "jpeg").lower() == "jpeg" else "png"
    return {
        "prompt": prompt,
        "model": t2i.get(f"{profile}_model"),
        "provider": provider,
        "api_key": MediaEngine._resolve_api_key(provider, user.encrypted_api_keys or {}),
        "adventure_id": state.session_id,
        "target_dir": safe_data_path(
            "adventures", "sessions", state.session_id, "visuals", "illustrations"
        ),
        "filename": f"moment_{uuid4().hex}.{ext}",
        "provider_options": options,
        "style_instruction": style,
    }, t2i


async def prepare_moment_prompt(request: dict) -> None:
    """One adaptation uses the configured Small/Utility deadline."""
    options = request["provider_options"]
    rules = prompt_rules(options) if request["provider"] == "comfyui" else None
    instructions = source_quality.INSTRUCTIONS
    policy = ImagePromptRules(
        format="description",
        language="English",
        max_words=150,
        instructions=instructions,
    )
    kwargs = {}
    if rules and rules.adapt_with_llm:
        policy = rules.model_copy(update={"instructions": instructions + "\n" + rules.instructions})
        kwargs["mature_themes"] = getattr(select_profile(options), "mature_themes", False)
        kwargs["nsfw_enabled"] = bool(options.get("_nsfw_enabled", False))
        kwargs["nsfw_level"] = str(options.get("_nsfw_level") or "hard")
    request["prompt"] = await adapt_body(
        request["prompt"], policy, options["_prompt_user"], **kwargs
    )
    # ComfyUI must still assemble mandatory prefix/suffix tokens, but must not
    # reinterpret this already distilled final frame in a second LLM call.
    options["_prompt_prepared"] = True
