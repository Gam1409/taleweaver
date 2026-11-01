"""Build a moment illustration using the story's existing image provider and style."""

import json
from uuid import uuid4

from backend.core.comfyui_config import prompt_rules, select_profile
from backend.core.image_prompt_rules import ImagePromptRules
from backend.core.visual_trace import record
from backend.engine.clothing.frames import extract_frame
from backend.engine.image_profiles import advanced_for
from backend.engine.image_prompt_adapter import adapt_body
from backend.engine.media_engine import MediaEngine
from backend.engine.session_portraits import _settings
from backend.engine.visual_novel.config import read_settings
from backend.utils.path_security import safe_data_path

from . import fidelity, source_quality
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
    prompt = (
        ""
        if read_settings(state).visual_preparation == "plan"
        else source_quality.build_prompt(context, style)
    )
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
        "_scene_facts": context.facts,
        "_scene_passage": context.passage,
    }, t2i


async def prepare_moment_prompt(request: dict) -> None:
    """Validate the prepared prompt, with one bounded feedback retry."""
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
    facts = request.get("_scene_facts")
    if facts is not None:
        policy = policy.model_copy(
            update={
                "instructions": policy.instructions
                + fidelity.requirements(facts, prompt_format=policy.format)
            }
        )
    source = request["prompt"]
    passage = request.pop("_scene_passage", "")
    if facts and "staging_status" in facts and passage and len(passage) <= 16000:
        frame = await extract_frame(options["_prompt_user"], passage, facts.get("characters", []))
        source += (
            "\nEPHEMERAL COMPOSITION (saved posture/placement still takes precedence): "
            + json.dumps(frame.model_dump(), ensure_ascii=False)
        )
    for attempt in range(2):
        body = await adapt_body(source, policy, options["_prompt_user"], **kwargs)
        diff = (
            await fidelity.differences(
                body, facts, options["_prompt_user"], prompt_format=policy.format
            )
            if facts is not None
            else []
        )
        record("fidelity.result", attempt=attempt + 1, differences=diff)
        if not diff:
            request["prompt"] = body
            break
        source += "\nCorrect these missing or conflicting facts: " + "; ".join(diff)
    else:
        raise ValueError(
            "The image description did not preserve the saved scene after a retry. No image was submitted. Try again or review the scene facts."
        )
    request.pop("_scene_facts", None)
    # ComfyUI must still assemble mandatory prefix/suffix tokens, but must not
    # reinterpret this already distilled final frame in a second LLM call.
    options["_prompt_prepared"] = True
