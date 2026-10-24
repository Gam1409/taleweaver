"""Adapt content to a chosen image model; assemble mandatory tokens deterministically."""

import asyncio
import json
import re

from backend.core import prompts
from backend.core.comfyui_config import prompt_rules, select_profile, select_workflow
from backend.core.image_prompt_rules import ImagePromptRules
from backend.core.llm_router import GameMasterLLM
from backend.engine.image_profiles import advanced_for

PROMPT_TIMEOUT = 90
MATURE_THEMES_INSTRUCTION = (
    "When consistent with the supplied scene, allow romantic tension, flirting and implied "
    "intimacy between clearly adult characters. Do not add sexual context on your own. "
    "Do not describe sexual acts, intimate anatomy or graphic sexual details. "
    "Do not sexualize minors or age-ambiguous characters."
)


def cover_source(title: str, original_prompt: str, provider: str, options: dict) -> str:
    if provider == "comfyui" and prompt_rules(options):
        if options.get("_prompt_prepared"):
            return original_prompt
        return f"Cover illustration for {title}. {str(original_prompt or '')[:1600]}"
    # Preserve legacy trimming, including removal of structured storyboard blocks.
    clean = str(original_prompt or "").strip()
    tag = re.search(r"\[(?:Sequence|Scene|NPC|Item|Quest)\b", clean, flags=re.IGNORECASE)
    if tag:
        clean = clean[: tag.start()].strip()
    clean = clean or str(original_prompt or "").strip()
    if len(clean) > 400:
        clean = clean[:400].rsplit(".", 1)[0] + "." if "." in clean[:400] else clean[:400]
    return prompts.ADVENTURE_COVER_PROMPT_TEMPLATE.format(title=title, original_prompt=clean)


def asset_source(t2i: dict, kind: str, legacy: str, **facts) -> str:
    profile = "advanced" if advanced_for(t2i, kind) else "simple"
    if t2i.get(f"{profile}_model_provider") != "comfyui":
        return legacy
    rules = prompt_rules({**t2i, "comfyui_profile": profile})
    if not rules:
        return legacy
    if not rules.adapt_with_llm:
        # Raw metadata keys/names can become unwanted captions in image models.
        body = str(facts.get("description") or legacy).strip()
        if kind in ("npc", "protagonist"):
            body += " " + prompts.PORTRAIT_COMPOSITION_INSTRUCTION
        return body
    if kind in ("npc", "protagonist"):
        facts["composition_instruction"] = prompts.PORTRAIT_COMPOSITION_INSTRUCTION
    return json.dumps({"asset_type": kind, **facts}, ensure_ascii=False)


async def adapt_body(
    description: str, rules: ImagePromptRules, user, *, mature_themes: bool = False
) -> str:
    if not rules.adapt_with_llm:
        return description.strip()
    if user is None:
        raise ValueError("Prompt adaptation requires configured Small/Utility LLM settings.")
    llm = GameMasterLLM.for_role(user, "small")
    policy = rules.model_dump(include={"format", "language", "max_words", "instructions"})
    system = (
        "Write only the body of an image-generation prompt following this policy: "
        + json.dumps(policy, ensure_ascii=False)
        + "\nPreserve the supplied visible facts, counts, identities, clothing and objects. "
        "Do not invent characters, franchise tags or objects. Do not reveal plot secrets. "
        "Use comma-separated visual tags for tags mode, connected sentences for description, "
        "or a short description followed by tags for hybrid. Ignore legacy aspect-ratio, "
        "quality and rendering boilerplate in the source. Do not output JSON, markdown, "
        "analysis, technical settings, weights, LoRA syntax or trigger/quality tokens; "
        "mandatory tokens are added separately. Avoid lettering unless explicitly requested."
    )
    if mature_themes:
        system += "\n" + MATURE_THEMES_INSTRUCTION
    try:
        body = await asyncio.wait_for(
            llm.aexecute_simple_task(
                system_prompt=system, user_prompt=description, model=llm.model
            ),
            timeout=PROMPT_TIMEOUT,
        )
    except TimeoutError as exc:
        raise TimeoutError(
            f"Small/Utility LLM image-prompt preparation timed out (limit: {PROMPT_TIMEOUT}s). "
            "No ComfyUI image job was submitted."
        ) from exc
    if not isinstance(body, str) or not body.strip() or len(body) > 12000:
        raise ValueError("The prompt adapter returned an empty or invalid description.")
    # This is a word budget, not a model-specific tokenizer/context guarantee.
    return " ".join(body.strip().split()[: rules.max_words])


def assemble_prompt(body: str, rules: ImagePromptRules) -> str:
    separator = ", " if rules.format == "tags" else " "
    return separator.join(
        part.strip(" ,\n") for part in (rules.prefix, body, rules.suffix) if part.strip()
    )


def negative_prompt(options: dict, extra: str = "") -> str:
    workflow = select_workflow(options, reference=bool(options.get("reference_image_url")))
    binding = workflow.bindings.get("negative_prompt")
    original = workflow.graph[binding.node_id]["inputs"][binding.input_name] if binding else ""
    parts = dict.fromkeys(
        part.strip()
        for part in (original, options.get("negative_prompt") or "", extra)
        if part.strip()
    )
    return ", ".join(parts)


async def prepare_prompt(description: str, options: dict) -> dict[str, str]:
    rules = prompt_rules(options)
    if not rules:
        return {"body": description, "positive": description, "negative": negative_prompt(options)}
    body = description
    if not options.get("_prompt_prepared"):
        body = await adapt_body(
            description,
            rules,
            options.get("_prompt_user"),
            mature_themes=getattr(select_profile(options), "mature_themes", False),
        )
    return {
        "body": body,
        "positive": assemble_prompt(body, rules),
        "negative": negative_prompt(options, rules.negative_prompt),
    }
