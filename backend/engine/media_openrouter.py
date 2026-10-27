"""OpenRouter image requests, compatibility retries, and chat image responses."""

import asyncio
import logging
import re
from typing import Any, Optional

import requests

from backend.core.config import settings

logger = logging.getLogger(__name__)


async def _generate_image_openrouter_direct(
    engine,
    prompt: str,
    model: str,
    api_key: Optional[str],
    target_dir: str,
    filename: Optional[str] = None,
    provider_options: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """Generates an image via OpenRouter's dedicated /api/v1/images endpoint."""
    provider_options = provider_options or {}
    image_format = provider_options.get("image_format", "jpeg")
    image_quality = provider_options.get("image_quality", 85)

    clean_model = model
    if clean_model.startswith("openrouter/"):
        clean_model = clean_model[len("openrouter/") :]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://taleweaver.local",
        "X-Title": "TaleWeaver",
    }

    payload: dict[str, Any] = {
        "model": clean_model,
        "prompt": prompt,
    }

    width = provider_options.get("width")
    height = provider_options.get("height")
    if width and height:
        payload["size"] = f"{width}x{height}"
    elif provider_options.get("aspect_ratio"):
        payload["aspect_ratio"] = provider_options["aspect_ratio"]

    logger.info(
        "Calling OpenRouter image endpoint (https://openrouter.ai/api/v1/images) for model %s",
        clean_model,
    )

    response = await asyncio.to_thread(
        requests.post,
        "https://openrouter.ai/api/v1/images",
        headers=headers,
        json=payload,
        timeout=settings.VISUAL_TIMEOUT,
    )

    if response.status_code != 200:
        response, error_msg = await _retry_rejected_dimensions(
            response, payload, headers, clean_model, prompt
        )
        if response.status_code != 200:
            # If OpenRouter explicitly informs that it's a chat model or cannot be used with /images, try chat fallback
            if "chat/completions" in error_msg.lower() or "modalities" in error_msg.lower():
                logger.info(
                    "Falling back to chat/completions with modalities=['image'] for %s", clean_model
                )
                return await engine._generate_image_openrouter_chat_fallback(
                    prompt=prompt,
                    model=model,
                    api_key=api_key,
                    target_dir=target_dir,
                    filename=filename,
                    provider_options=provider_options,
                )

            raise RuntimeError(f"OpenRouter image generation failed: {error_msg}")

    return await _save_openrouter_result(
        engine, response, target_dir, filename, image_format, image_quality
    )


async def _generate_image_openrouter_chat_fallback(
    engine,
    prompt: str,
    model: str,
    api_key: Optional[str],
    target_dir: str,
    filename: Optional[str] = None,
    provider_options: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """Fallback image generation using OpenRouter /v1/chat/completions with modalities=['image']."""
    provider_options = provider_options or {}
    kwargs: dict[str, Any] = {
        "model": f"openrouter/{model}" if not model.startswith("openrouter/") else model,
        "messages": [{"role": "user", "content": prompt}],
        "modalities": ["image"],
        "api_base": "https://openrouter.ai/api/v1",
    }
    if api_key:
        kwargs["api_key"] = api_key

    image_config = {}
    if provider_options.get("width") and provider_options.get("height"):
        image_config["image_size"] = f"{provider_options['width']}x{provider_options['height']}"
    if image_config:
        kwargs["image_config"] = image_config

    response = await asyncio.to_thread(engine._get_litellm().completion, **kwargs)
    logger.info("OpenRouter completion finished")

    image_url, b64_data = _chat_image_payload(response.choices[0].message)

    image_format = provider_options.get("image_format", "jpeg")
    image_quality = provider_options.get("image_quality", 85)

    if image_url:
        return await engine._save_remote_image(
            image_url, target_dir, filename, image_format, image_quality
        )
    if b64_data:
        return await engine._save_b64_image(
            b64_data, target_dir, filename, image_format, image_quality
        )

    raise RuntimeError("OpenRouter generation failed to return an image.")


async def _retry_rejected_dimensions(response, payload, headers, clean_model, prompt):
    error_msg = f"HTTP {response.status_code}"
    try:
        err_data = response.json()
        if isinstance(err_data, dict) and "error" in err_data:
            err_obj = err_data["error"]
            if isinstance(err_obj, dict) and "message" in err_obj:
                error_msg = err_obj["message"]
            elif isinstance(err_obj, str):
                error_msg = err_obj
    except Exception:
        error_msg = response.text[:300]

    logger.warning(
        "OpenRouter /api/v1/images endpoint returned error (%s): %s",
        response.status_code,
        error_msg,
    )

    # If parameter error with size/aspect_ratio, retry with minimal payload (model + prompt)
    if response.status_code == 400 and ("size" in payload or "aspect_ratio" in payload):
        logger.info(
            "Retrying OpenRouter /api/v1/images with minimal payload due to parameter rejection: %s",
            error_msg,
        )
        retry_payload = {"model": clean_model, "prompt": prompt}
        retry_resp = await asyncio.to_thread(
            requests.post,
            "https://openrouter.ai/api/v1/images",
            headers=headers,
            json=retry_payload,
            timeout=settings.VISUAL_TIMEOUT,
        )
        if retry_resp.status_code == 200:
            response = retry_resp
        else:
            try:
                r_err = retry_resp.json().get("error", {})
                error_msg = (
                    r_err.get("message", retry_resp.text[:300])
                    if isinstance(r_err, dict)
                    else str(r_err)
                )
            except Exception:
                error_msg = retry_resp.text[:300]

    return response, error_msg


async def _save_openrouter_result(
    engine, response, target_dir, filename, image_format, image_quality
):
    result = response.json()
    data_list = result.get("data", [])
    if not data_list or not isinstance(data_list, list):
        logger.error("OpenRouter response missing 'data' list: %s", result)
        raise RuntimeError("OpenRouter response did not contain image data.")

    first_img = data_list[0]
    if isinstance(first_img, dict):
        b64_json = first_img.get("b64_json")
        if b64_json:
            return await engine._save_b64_image(
                b64_json, target_dir, filename, image_format, image_quality
            )

        image_url = first_img.get("url")
        if image_url:
            if image_url.startswith("data:image/"):
                return await engine._save_b64_image(
                    image_url, target_dir, filename, image_format, image_quality
                )
            return await engine._save_remote_image(
                image_url, target_dir, filename, image_format, image_quality
            )

    raise RuntimeError("No valid image data or URL found in OpenRouter response.")


def _images_field_url(images):
    if not isinstance(images, list):
        return None
    for item in images:
        if not isinstance(item, dict):
            continue
        image = item.get("image_url") or item
        if isinstance(image, dict) and image.get("url"):
            return image["url"]
    return None


def _content_item_dict(item):
    if hasattr(item, "model_dump"):
        return item.model_dump()
    if hasattr(item, "dict"):
        return item.dict()
    if isinstance(item, dict):
        return item
    return getattr(item, "__dict__", {})


def _content_image_url(content):
    if not isinstance(content, list):
        return None
    for item in content:
        item_dict = _content_item_dict(item)
        if item_dict.get("type") != "image_url":
            continue
        image = item_dict.get("image_url", {})
        url = image.get("url") if isinstance(image, dict) else getattr(image, "url", None)
        url = url or item_dict.get("url")
        if url:
            return url
    return None


def _chat_image_payload(message):
    content = getattr(message, "content", "")
    url = _images_field_url(getattr(message, "images", [])) or _content_image_url(content)
    if url:
        return (None, url) if url.startswith("data:image/") else (url, None)
    url_match = re.search(r'https?://[^\s)"\']+\.(?:jpg|jpeg|png|webp)', str(content))
    if url_match:
        return url_match.group(0), None
    if "data:image/" in str(content):
        data_match = re.search(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]+", str(content))
        if data_match:
            return None, data_match.group(0)
    return None, None
