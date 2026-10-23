"""Editable starting points, not guarantees for every derivative checkpoint."""

from backend.core.image_prompt_rules import ImagePromptRules


def _template(
    key,
    name,
    format,
    instructions,
    *,
    words=100,
    prefix="",
    suffix="",
    negative="",
    source="",
    notes="",
):
    return {
        "id": key,
        "name": name,
        "source": source,
        "notes": notes,
        "rules": ImagePromptRules(
            template_id=key,
            format=format,
            instructions=instructions,
            max_words=words,
            prefix=prefix,
            suffix=suffix,
            negative_prompt=negative,
        ).model_dump(),
    }


TEMPLATES = [
    _template(
        "natural",
        "Natural description",
        "description",
        "Describe subject, action, spatial relationships, setting, lighting and composition in that order.",
        notes="A neutral starting point. Check the exact model's documentation.",
    ),
    _template(
        "sd15",
        "Stable Diffusion 1.5 — concise",
        "hybrid",
        "Put the subject and essential visual attributes first. Use a concise description with a few concrete style tags.",
        words=55,
        negative="text, watermark, signature",
        source="https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5",
        notes="Conservative base-model template. Derivatives may require their own tags; word count is not a token limit.",
    ),
    _template(
        "sdxl",
        "SDXL — description and tags",
        "hybrid",
        "Describe the main subject and composition, then add concise lighting and style cues. Avoid contradictory framing.",
        words=80,
        negative="text, watermark, signature",
        source="https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0",
        notes="General SDXL starting point, including manual adaptation for realistic derivatives. No universal quality tokens.",
    ),
    _template(
        "flux1",
        "FLUX.1 — natural description",
        "description",
        "Use clear connected sentences with subject, action, relationships, environment, lighting and desired visual style. Avoid tag soup and quality-score tokens.",
        words=140,
        source="https://docs.comfy.org/tutorials/flux/flux-1-text-to-image",
        notes="For text-to-image FLUX.1 workflows. Guidance, weights and negative conditioning depend on the workflow.",
    ),
    _template(
        "sd35",
        "Stable Diffusion 3.5 — natural description",
        "description",
        "Write precise connected sentences. Describe subject and action first, then spatial arrangement, environment, lighting and style.",
        words=140,
        source="https://huggingface.co/stabilityai/stable-diffusion-3.5-large",
        notes="Conservative starting point; the gated model card could not be checked in this environment. Verify derivative-specific guidance.",
    ),
    _template(
        "pony6",
        "Pony Diffusion V6 XL — score tags",
        "tags",
        "Use concise visual tags. Put subject count, visible appearance, clothing, action, environment and composition in order. Do not invent franchise, artist or source tags.",
        words=90,
        prefix="score_9, score_8_up, score_7_up",
        negative="text, watermark, signature",
        source="https://huggingface.co/AstraliteHeart/pony-diffusion-v6-xl",
        notes="Common V6 community convention; author card was unavailable during review. Scores are not universal to Pony derivatives or Illustrious.",
    ),
    _template(
        "illustrious",
        "Illustrious XL — visual tags",
        "tags",
        "Use visual tags for subject count, appearance, clothing, action and setting. Select one compatible composition, such as portrait or full body. Do not add Pony score tokens or invent artist/franchise tags.",
        words=90,
        negative="worst quality, bad quality, lowres, text, watermark, signature",
        source="https://huggingface.co/OnomaAIResearch/Illustrious-xl-early-release-v0",
        notes="Based on the public early-release card. Quality tags are optional; derivatives can differ.",
    ),
    _template(
        "animagine4",
        "Animagine XL 4.0 — ordered tags",
        "tags",
        "Start with the actual subject count/type, then known identity only if supplied, appearance, clothing, action, setting and composition. Do not invent a series, rating, artist or character identity. Quality tokens are appended separately.",
        words=90,
        suffix="masterpiece, high score, great score, absurdres",
        negative="lowres, bad anatomy, bad hands, text, error, worst quality, low quality, low score, bad score, signature, watermark, blurry",
        source="https://huggingface.co/cagliostrolab/animagine-xl-4.0",
        notes="Uses the author's 4.0 ordering and quality suffix. Other Animagine versions need separate rules.",
    ),
    _template(
        "qwen_image",
        "Qwen-Image — detailed description",
        "description",
        "Use connected sentences with precise counts, attributes, spatial relationships, action and lighting. Preserve all visible details without inventing text in the image.",
        words=160,
        source="https://huggingface.co/Qwen/Qwen-Image",
        notes="Text-to-image starting point. Qwen-Image-Edit requires explicit change/preservation instructions and a matching image workflow.",
    ),
]


def template_rules(template_id: str) -> ImagePromptRules:
    item = next((item for item in TEMPLATES if item["id"] == template_id), None)
    if not item:
        raise ValueError("Unknown image prompt template.")
    return ImagePromptRules.model_validate(item["rules"])
