"""Build a moment illustration using the story's existing image provider and style."""

import json
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.comfyui_config import prompt_rules, select_profile
from backend.core.image_prompt_rules import ImagePromptRules
from backend.core.visual_trace import record
from backend.engine.clothing.frames import extract_frame
from backend.engine.image_profiles import advanced_for
from backend.engine.image_prompt_adapter import adapt_body
from backend.engine.media_engine import MediaEngine
from backend.engine.session_portraits import _settings
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.utils.path_security import safe_data_path

from . import fidelity, nsfw_guard, source_quality
from .visual_context import VisualContext


async def image_request(
    db: AsyncSession, state: SessionState, user: User, snapshot: dict
) -> tuple[dict, dict]:
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
    prompt = "" if not t2i.get("_nsfw_enabled") else source_quality.build_prompt(context, style)
    if t2i.get("_nsfw_enabled"):
        from backend.engine.visual_novel.config import read_settings

        options["_nsfw_guard_mode"] = read_settings(state).nsfw_guard
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


def _visual_mature_themes(options: dict) -> bool:
    """The Visual settings gate: mature themes on the selected image profile."""
    try:
        return bool(getattr(select_profile(options), "mature_themes", False))
    except Exception:  # Malformed visual settings cannot enable the guard.
        return False


def _guard_atoms(options: dict, facts: dict | None) -> tuple[str, list[dict]]:
    """Guard mode and sanitized explicit atoms; empty atoms disable the check.

    Mirrors the image addendum gate: explicit-atom machinery activates only
    when the adventure enables NSFW and the selected Visual profile enables
    mature themes. Sessions whose visual layer renders non-explicit images
    never receive explicit-content requirements.
    """
    mode = str(options.get("_nsfw_guard_mode") or "warn")
    if (
        facts is None
        or not options.get("_nsfw_enabled")
        or not _visual_mature_themes(options)
        or mode == "off"
    ):
        return mode, []
    return mode, nsfw_guard.explicit_atoms(facts)


async def _attempt_diffs(
    body: str,
    facts: dict | None,
    atoms: list[dict],
    options: dict,
    prompt_format: str,
) -> tuple[list[str], list[str]]:
    """Literal fidelity and explicit-guard differences for one attempt."""
    diff = (
        await fidelity.differences(
            body, facts, options["_prompt_user"], prompt_format=prompt_format
        )
        if facts is not None
        else []
    )
    guard_missing = nsfw_guard.differences(
        body, atoms, facts.get("characters", []) if facts else []
    )
    return diff, guard_missing


def _finalize_body(
    request: dict,
    body: str,
    *,
    passed: bool,
    diff: list[str],
    guard_missing: list[str],
    guard_mode: str,
) -> None:
    """Set the final prompt; refuse renders that lost required facts."""
    if passed:
        return
    if diff:
        raise ValueError(
            "The image description did not preserve the saved scene after a retry. No image was submitted. Try again or review the scene facts."
        )
    if guard_missing and guard_mode == "block":
        raise ValueError(
            "The image description lost required explicit scene facts after a retry. No image was submitted. Try again or review the scene facts."
        )
    # Shadow mode: proceed with the last body; the failure stays recorded.
    request["prompt"] = body


async def prepare_moment_prompt(request: dict) -> None:
    """Validate the prepared prompt, with one bounded feedback retry."""
    options = request["provider_options"]
    rules = prompt_rules(options) if request["provider"] == "comfyui" else None
    facts = request.get("_scene_facts")
    guard_mode, atoms = _guard_atoms(options, facts)
    instructions = source_quality.INSTRUCTIONS
    if atoms:
        # The explicit-atom contract below governs mature scenes; carrying the
        # neutral "non-graphic" framing into it would instruct the adapter to
        # soften the very acts the guard verifies.
        instructions = instructions.replace(
            "Create a non-graphic illustration",
            "Create an explicit mature-content illustration",
        )
    policy = ImagePromptRules(
        format="description",
        language="English",
        max_words=150,
        instructions=instructions,
    )
    kwargs: dict[str, Any] = {}
    if rules and rules.adapt_with_llm:
        policy = rules.model_copy(update={"instructions": instructions + "\n" + rules.instructions})
        kwargs["mature_themes"] = getattr(select_profile(options), "mature_themes", False)
        kwargs["nsfw_enabled"] = bool(options.get("_nsfw_enabled", False))
        kwargs["nsfw_level"] = str(options.get("_nsfw_level") or "hard")
    if facts is not None:
        extra = fidelity.requirements(facts, prompt_format=policy.format)
        if atoms:
            extra += nsfw_guard.requirements(atoms, facts.get("characters", []))
        policy = policy.model_copy(update={"instructions": policy.instructions + extra})
    source = request["prompt"]
    passage = request.pop("_scene_passage", "")
    if facts and "staging_status" in facts and passage and len(passage) <= 16000:
        frame = await extract_frame(options["_prompt_user"], passage, facts.get("characters", []))
        source += (
            "\nEPHEMERAL COMPOSITION (saved posture/placement still takes precedence): "
            + json.dumps(frame.model_dump(), ensure_ascii=False)
        )
    guard = nsfw_guard.status(guard_mode, atoms, [])
    diff: list[str] = []
    guard_missing: list[str] = []
    passed = False
    for attempt in range(2):
        body = await adapt_body(source, policy, options["_prompt_user"], **kwargs)
        diff, guard_missing = await _attempt_diffs(body, facts, atoms, options, policy.format)
        guard = nsfw_guard.status(guard_mode, atoms, guard_missing)
        combined = diff + guard_missing
        record("fidelity.result", attempt=attempt + 1, differences=combined)
        if not combined:
            request["prompt"] = body
            passed = True
            break
        source += "\nCorrect these missing or conflicting facts: " + "; ".join(combined)
    details = options.get("_generation_details")
    if isinstance(details, dict):
        details["nsfw_guard"] = guard
    record("nsfw_guard.result", **guard)
    _finalize_body(
        request,
        body,
        passed=passed,
        diff=diff,
        guard_missing=guard_missing,
        guard_mode=guard_mode,
    )
    request.pop("_scene_facts", None)
    # ComfyUI must still assemble mandatory prefix/suffix tokens, but must not
    # reinterpret this already distilled final frame in a second LLM call.
    options["_prompt_prepared"] = True
