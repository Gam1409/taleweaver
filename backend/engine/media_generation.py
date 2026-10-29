"""Image prompt preparation, provider routing, and provider-specific fallback policy."""

import asyncio
import logging
from typing import Any, Optional

from backend.core.comfyui_config import prompt_rules
from backend.core.config import settings

logger = logging.getLogger(__name__)


async def generate_image(
    engine,
    prompt: str,
    model: str,
    api_key: Optional[str],
    provider: str = "openai",
    adventure_id: Optional[str] = None,
    target_dir: Optional[str] = None,
    filename: Optional[str] = None,
    provider_options: Optional[dict[str, Any]] = None,
    style_instruction: Optional[str] = None,
) -> Optional[str]:
    """Generates an image and saves it locally."""
    from backend.engine.media_engine import (
        _resolve_output_dir,
        _safe_data_path,
        _safe_prompt_summary,
    )

    provider_key = (provider or "openai").lower()
    if not prompt or (not model and provider_key != "comfyui"):
        raise ValueError("Missing prompt or model for image generation.")

    prompt = _prepare_prompt(engine, prompt, provider_key, provider_options, style_instruction)

    _record_prompt_details(provider_options, provider_key, model, prompt)

    if provider_key not in ("ollama", "stable_diffusion", "comfyui") and not api_key:
        # Try to resolve from ENV if not passed
        api_key = settings.get_env_api_key(provider_key)
        if not api_key:
            raise ValueError(f"Missing API key for image generation provider '{provider_key}'.")

    _validate_ollama_model(provider_key, model, prompt)

    # Default target dir if not provided
    if target_dir is None:
        if adventure_id:
            target_dir = _safe_data_path("adventures", "library", adventure_id)
        else:
            target_dir = _safe_data_path("adventures", "library")
    else:
        target_dir = _resolve_output_dir(target_dir)

    logger.info(
        "Generating image with model %s (provider: %s, prompt_%s)",
        model,
        provider_key,
        _safe_prompt_summary(prompt),
    )

    try:
        provider_options = provider_options or {}

        return await _generate_with_provider(
            engine, prompt, model, api_key, provider_key, target_dir, filename, provider_options
        )

    except Exception as e:
        error_str = str(e)
        if provider_key == "ollama":
            logger.warning("LiteLLM ollama path failed; trying direct Ollama API fallback.")
            direct_result = await engine._generate_image_ollama_direct(
                prompt=prompt,
                model=model,
                ollama_url=(provider_options or {}).get("ollama_url") or "http://localhost:11434",
                target_dir=target_dir,
                filename=filename,
                width=(provider_options or {}).get("width"),
                height=(provider_options or {}).get("height"),
                steps=(provider_options or {}).get("steps"),
                seed=(provider_options or {}).get("seed"),
                negative_prompt=(provider_options or {}).get("negative_prompt"),
            )
            if direct_result:
                return direct_result
            raise RuntimeError(
                f"Ollama image generation failed for model '{model}'. Original error: {error_str}"
            ) from e
        err_lower = error_str.lower()
        if (
            "content moderated" in err_lower
            or "safety filter" in err_lower
            or "moderated" in err_lower
        ):
            logger.warning("Image generation was moderated (Safety Filter).")
            raise ValueError(
                "Image generation was blocked by the AI provider's safety filter. "
                "Please adjust the description to avoid sensitive content."
            ) from e
        logger.error("Image generation failed (%s)", type(e).__name__)
        raise


async def _generate_with_provider(
    engine, prompt, model, api_key, provider_key, target_dir, filename, provider_options
):
    if provider_key == "comfyui":
        from backend.engine.comfyui_images import generate_comfy_image

        return await generate_comfy_image(prompt, provider_options, target_dir, filename)

    if provider_key == "openrouter":
        return await engine._generate_image_openrouter_direct(
            prompt=prompt,
            model=model,
            api_key=api_key,
            target_dir=target_dir,
            filename=filename,
            provider_options=provider_options,
        )

    if provider_key == "black_forest_labs":
        return await engine._generate_image_black_forest_labs_direct(
            prompt=prompt,
            model=model,
            api_key=api_key,
            target_dir=target_dir,
            filename=filename,
            provider_options=provider_options,
        )

    if provider_key == "stable_diffusion":
        sd_url = provider_options.get("stable_diffusion_url") or "http://127.0.0.1:7860"
        image_format = provider_options.get("image_format", "jpeg")
        image_quality = provider_options.get("image_quality", 85)
        return await engine._generate_image_stable_diffusion_direct(
            prompt=prompt,
            model=model,
            stable_diffusion_url=sd_url,
            target_dir=target_dir,
            filename=filename,
            width=provider_options.get("width"),
            height=provider_options.get("height"),
            steps=provider_options.get("steps") if provider_options.get("steps") is not None else 4,
            cfg_scale=provider_options.get("cfg_scale")
            if provider_options.get("cfg_scale") is not None
            else 1.0,
            seed=provider_options.get("seed"),
            negative_prompt=provider_options.get("negative_prompt"),
            image_format=image_format,
            image_quality=image_quality,
            sampler_name=provider_options.get("sampler_name") or "Euler",
            scheduler=provider_options.get("scheduler") or "Normal",
        )

    return await _generate_with_litellm(
        engine, prompt, model, api_key, provider_key, target_dir, filename, provider_options
    )


async def _generate_with_litellm(
    engine, prompt, model, api_key, provider_key, target_dir, filename, provider_options
):
    from backend.engine.media_engine import _safe_prompt_summary

    kwargs: dict[str, Any] = {
        "prompt": prompt,
        "model": model,
        "custom_llm_provider": provider_key,
    }
    if api_key:
        kwargs["api_key"] = api_key

    # Pass common optional generation controls through when available.
    optional_fields = ("width", "height", "steps", "seed", "negative_prompt")
    for field in optional_fields:
        value = provider_options.get(field)
        if value is not None:
            kwargs[field] = value

    if provider_key == "ollama":
        ollama_url = (provider_options.get("ollama_url") or "http://localhost:11434").rstrip("/")
        kwargs["api_base"] = ollama_url

    logger.info(
        "Final image generation config: provider=%s model=%s prompt=%s controls=%s",
        provider_key,
        model,
        _safe_prompt_summary(prompt),
        {
            "width": "width" in kwargs,
            "height": "height" in kwargs,
            "steps": "steps" in kwargs,
            "seed": "seed" in kwargs,
            "negative_prompt": "negative_prompt" in kwargs,
            "api_base": "api_base" in kwargs,
        },
    )

    # Call LiteLLM first - wrap in to_thread because LiteLLM image_generation is synchronous
    response = await asyncio.to_thread(
        engine._get_litellm().image_generation,
        **kwargs,
        request_timeout=settings.VISUAL_TIMEOUT,
    )
    image_url, b64_json = engine._extract_image_payload(response)

    image_format = provider_options.get("image_format", "jpeg")
    image_quality = provider_options.get("image_quality", 85)

    if image_url:
        return await engine._save_remote_image(
            image_url, target_dir, filename, image_format, image_quality
        )
    elif b64_json:
        return await engine._save_b64_image(
            b64_json, target_dir, filename, image_format, image_quality
        )
    elif provider_key == "ollama":
        logger.warning(
            "LiteLLM returned no image payload for ollama; trying direct Ollama API fallback."
        )
        direct_result = await engine._generate_image_ollama_direct(
            prompt=prompt,
            model=model,
            ollama_url=provider_options.get("ollama_url") or "http://localhost:11434",
            target_dir=target_dir,
            filename=filename,
            width=provider_options.get("width"),
            height=provider_options.get("height"),
            steps=provider_options.get("steps"),
            seed=provider_options.get("seed"),
            negative_prompt=provider_options.get("negative_prompt"),
        )
        if direct_result:
            return direct_result
        raise RuntimeError("Ollama image generation returned no image payload.")
    else:
        logger.error("No image data in provider response")
        return None


def _prepare_prompt(engine, prompt, provider_key, provider_options, style_instruction):
    from backend.engine.media_engine import _safe_prompt_summary

    # Inject style instruction if provided
    adapted = provider_key == "comfyui" and prompt_rules(provider_options or {})
    manual_adapted = adapted and (provider_options or {}).get("_prompt_prepared")
    if style_instruction and style_instruction not in prompt and not manual_adapted:
        # Ensure we don't have multiple dots
        prompt = prompt.strip()
        while prompt.endswith("."):
            prompt = prompt[:-1].strip()
        prompt += f". Style: {style_instruction}."
        logger.info("Style instruction injected")

    if not adapted:
        prompt = engine._apply_no_text_instruction(prompt)
    logger.info("Image prompt prepared (%s)", _safe_prompt_summary(prompt))

    return prompt


def _validate_ollama_model(provider_key, model, prompt):
    from backend.engine.media_engine import _safe_prompt_summary

    if provider_key == "ollama":
        logger.info("Generating image with local Ollama (%s)", _safe_prompt_summary(prompt))
        remote_prefixes = (
            "openai/",
            "openrouter/",
            "anthropic/",
            "google/",
            "gemini/",
            "azure/",
            "bedrock/",
            "cohere/",
        )
        if model.startswith(remote_prefixes):
            raise ValueError(
                f"Provider is 'ollama' but image model '{model}' looks like a remote/cloud model. "
                "Configure a local Ollama image model (for example: x/flux2-klein)."
            )


def _record_prompt_details(provider_options, provider_key, model, prompt):
    details = (provider_options or {}).get("_generation_details")
    if isinstance(details, dict) and provider_key != "comfyui":
        details.update(provider=provider_key, model=model, positive_prompt=prompt)
        if provider_key in {"ollama", "stable_diffusion"}:
            details["negative_prompt"] = (provider_options or {}).get("negative_prompt") or ""
