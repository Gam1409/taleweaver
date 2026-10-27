"""Direct Ollama and Stable Diffusion image requests."""

import asyncio
import logging
from typing import Any, Optional

import requests

from backend.core.config import settings

logger = logging.getLogger(__name__)


async def _generate_image_ollama_direct(
    engine,
    prompt: str,
    model: str,
    ollama_url: str,
    target_dir: str,
    filename: Optional[str] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    steps: Optional[int] = None,
    seed: Optional[int] = None,
    negative_prompt: Optional[str] = None,
) -> Optional[str]:
    """Generate an image through Ollama's local HTTP API."""
    try:
        base = ollama_url.rstrip("/")
        if not base.endswith("/api"):
            base = f"{base}/api"
        endpoint = f"{base}/generate"

        options: dict[str, Any] = {}
        for key, value in (("width", width), ("height", height), ("steps", steps), ("seed", seed)):
            if value is not None:
                options[key] = value
        if negative_prompt:
            options["negative_prompt"] = negative_prompt

        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
        }
        if options:
            payload["options"] = options

        response = await asyncio.to_thread(requests.post, endpoint, json=payload, timeout=120)
        if response.status_code != 200:
            logger.error(
                "Ollama direct image generation failed. status=%s",
                response.status_code,
            )
            return None

        body = response.json()
        image_url, b64_json = engine._extract_image_payload(body)

        image_format = "jpeg"
        image_quality = 85

        if image_url:
            return await engine._save_remote_image(
                image_url, target_dir, filename, image_format, image_quality
            )
        if b64_json:
            return await engine._save_b64_image(
                b64_json, target_dir, filename, image_format, image_quality
            )

        logger.error("Ollama response did not include image payload")
        return None
    except (requests.RequestException, OSError, TypeError, ValueError):
        logger.exception("Error during direct Ollama image generation")
        return None


async def _generate_image_stable_diffusion_direct(
    engine,
    prompt: str,
    model: str,
    stable_diffusion_url: str,
    target_dir: str,
    filename: Optional[str] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    steps: Optional[int] = None,
    cfg_scale: Optional[float] = None,
    seed: Optional[int] = None,
    negative_prompt: Optional[str] = None,
    image_format: str = "jpeg",
    image_quality: int = 85,
    sampler_name: Optional[str] = None,
    scheduler: Optional[str] = None,
) -> Optional[str]:
    """Generate an image through Stable Diffusion's local HTTP API."""
    try:
        base = stable_diffusion_url.rstrip("/")
        endpoint = f"{base}/sdapi/v1/txt2img"

        payload: dict[str, Any] = {
            "prompt": prompt,
        }
        for key, value in (
            ("width", width),
            ("height", height),
            ("steps", steps),
            ("cfg_scale", cfg_scale),
            ("seed", seed),
        ):
            if value is not None:
                payload[key] = value
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt
        if sampler_name:
            payload["sampler_name"] = sampler_name
        if scheduler:
            payload["scheduler"] = scheduler

        if model and model != "default":
            payload["override_settings"] = {"sd_model_checkpoint": model}

        response = await asyncio.to_thread(
            requests.post, endpoint, json=payload, timeout=settings.VISUAL_TIMEOUT
        )
        if response.status_code != 200:
            logger.error(
                "Stable Diffusion direct image generation failed. status=%s",
                response.status_code,
            )
            return None

        body = response.json()
        images = body.get("images")
        if not images or not isinstance(images, list):
            logger.error("Stable Diffusion response did not include image list")
            return None

        b64_json = images[0]
        return await engine._save_b64_image(
            b64_json, target_dir, filename, image_format=image_format, quality=image_quality
        )
    except Exception:
        logger.exception("Error during direct Stable Diffusion image generation")
        return None
