"""Freeze and verify the exact text at the existing image-provider submission seam."""

from backend.engine.image_prompt_adapter import prepare_prompt
from backend.engine.media_generation import _prepare_prompt

from .visual_plan import fingerprint


async def artifact(request: dict, body: str) -> dict:
    from backend.engine.media_engine import MediaEngine

    options = {**request["provider_options"], "_prompt_prepared": True}
    prepared = _prepare_prompt(
        MediaEngine, body, request["provider"], options, request.get("style_instruction")
    )
    texts = {"positive": prepared, "negative": submitted_negative(request["provider"], options)}
    if request["provider"] == "comfyui":
        texts = await prepare_prompt(prepared, options)
    return {
        "body": body,
        "media_hash": fingerprint(prepared),
        "positive": texts["positive"],
        "negative": texts["negative"],
        "text_hash": fingerprint([texts["positive"], texts["negative"]]),
    }


def verify_media(prompt: str, options: dict | None) -> None:
    expected = (options or {}).get("_visual_plan_artifact")
    if expected and fingerprint(prompt) != expected["media_hash"]:
        raise ValueError(
            "The image prompt changed after its visual audit. Rebuild the visual plan."
        )
    if expected and (options or {}).get("_visual_plan_provider") != "comfyui":
        verify_texts(
            prompt,
            submitted_negative((options or {}).get("_visual_plan_provider", ""), options or {}),
            options or {},
        )


def verify_texts(positive: str, negative: str, options: dict) -> None:
    expected = options.get("_visual_plan_artifact")
    if expected and fingerprint([positive, negative]) != expected["text_hash"]:
        raise ValueError(
            "The submitted image text differs from its audited artifact. Rebuild the visual plan."
        )


def submitted_negative(provider: str, options: dict) -> str:
    if provider in {"openrouter", "black_forest_labs"}:
        return ""
    return str(options.get("negative_prompt") or "")
