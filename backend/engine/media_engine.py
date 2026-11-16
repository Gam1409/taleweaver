"""
MediaEngine handles AI image generation for scenes and entities.
Integrated with LiteLLM to support OpenAI (DALL-E), OpenRouter, and Google (Imagen), while using the direct BFL API for Black Forest Labs.
"""

import asyncio
import logging
import os
import re
import uuid
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

import litellm
import requests

from backend.core import prompts
from backend.core.config import settings
from backend.core.image_purposes import image_provider, purpose_for
from backend.core.llm_diagnostics import async_operation
from backend.core.security import encryption_util
from backend.engine.bfl_payloads import resolve_bfl_model_alias
from backend.engine.image_prompt_adapter import cover_source
from backend.engine.media_file_operations import (
    decode_image_payload,
    list_thumbnail_sources,
    persist_image_bytes,
)
from backend.utils.async_files import run_file_operation
from backend.utils.path_security import (
    ensure_within_base_dir,
    local_path_to_data_url,
    sanitize_relative_segment,
)
from backend.utils.path_security import (
    ensure_within_data_dir as ensure_within_data_dir_shared,
)
from backend.utils.path_security import (
    sanitize_path_component as sanitize_path_component_shared,
)
from backend.utils.text_utils import slugify

logger = logging.getLogger(__name__)

BFL_DEFAULT_MODEL = "black_forest_labs/flux-pro-1.1"
BFL_API_BASE = "https://api.bfl.ai/v1"
# Use centralized prompts
NO_TEXT_IMAGE_PROMPT_SUFFIX = prompts.NO_TEXT_IMAGE_PROMPT_SUFFIX


_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")

_FRONTEND_SVG_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src", "assets", "svg")
)

_ITEM_PLACEHOLDER_ASSET_BY_TYPE = {
    "CONTAINER": "chest.svg",
    "COMBINABLE": "combinable.svg",
    "CONSTRUCTABLE": "constructable.svg",
    "CONSUMABLE": "potion.svg",
    "READABLE": "scroll.svg",
    "WEAPON": "sword.svg",
    "KEY": "key.svg",
}


def _sanitize_path_component(value: Optional[str]) -> Optional[str]:
    """Return a safe single path component, or None when invalid."""
    return sanitize_path_component_shared(value)


def _ensure_within_data_dir(path: str) -> str:
    """Validate that a path resolves inside DATA_DIR and return its absolute form."""
    return ensure_within_data_dir_shared(path)


def _safe_data_path(*parts: str) -> str:
    """Build a safe path under DATA_DIR."""
    safe_parts: list[str] = []
    for part in parts:
        safe_part = _sanitize_path_component(part)
        if not safe_part:
            raise ValueError("Invalid path component.")
        safe_parts.append(safe_part)
    return _ensure_within_data_dir(os.path.join(settings.DATA_DIR, *safe_parts))


def _normalize_output_filename(filename: Optional[str], extension: str) -> str:
    """Return a sanitized output filename with a safe image extension."""
    ext = "jpg" if extension.lower() == "jpeg" else extension.lower()
    candidate = (filename or "").strip()
    if not candidate:
        return f"{uuid.uuid4()}.{ext}"

    # Keep only the final segment to prevent directory traversal.
    candidate = os.path.basename(candidate)
    stem, _original_ext = os.path.splitext(candidate)
    stem = _SAFE_FILENAME_RE.sub("_", stem).strip("._")
    if not stem:
        stem = str(uuid.uuid4())

    # Always enforce trusted extension selected by server-side format.
    return f"{stem}.{ext}"


def _normalize_svg_filename(filename: Optional[str], default_stem: str) -> str:
    """Return a sanitized svg filename."""
    candidate = (filename or "").strip()
    if candidate:
        candidate = os.path.basename(candidate)
        stem, _ext = os.path.splitext(candidate)
        stem = _SAFE_FILENAME_RE.sub("_", stem).strip("._")
    else:
        stem = _SAFE_FILENAME_RE.sub("_", default_stem).strip("._")
    if not stem:
        stem = str(uuid.uuid4())
    return f"{stem}.svg"


def _select_static_placeholder_asset(category: str) -> Optional[str]:
    """Resolve static SVG placeholder source path for supported categories."""
    cat = (category or "").upper()
    if cat == "NPC":
        return os.path.join(_FRONTEND_SVG_ROOT, "npcs", "silhouette.svg")

    if cat == "ITEM":
        filename = "pouch.svg"
    elif cat.startswith("ITEM_"):
        item_type = cat.removeprefix("ITEM_").split("_", 1)[0]
        filename = _ITEM_PLACEHOLDER_ASSET_BY_TYPE.get(item_type, "pouch.svg")
    else:
        return None

    return os.path.join(_FRONTEND_SVG_ROOT, "items", filename)


def _is_svg_image_file(file_path: str, ext: str) -> bool:
    if ext.lower() == ".svg":
        return True
    if not os.path.isfile(file_path):
        return False
    try:
        with open(file_path, "rb") as f:
            return b"<svg" in f.read(512).lower()
    except OSError:
        return False


def _resolve_output_dir(target_dir: str) -> str:
    """Resolve an output directory to a validated location inside DATA_DIR."""
    candidate = str(target_dir or "").strip()
    if not candidate:
        raise ValueError("Target directory is required.")
    if ".." in candidate:
        raise ValueError("Directory traversal not allowed")
    if os.path.isabs(candidate):
        return _ensure_within_data_dir(candidate)

    # Check if candidate is relative to repository root but already starts with DATA_DIR
    candidate_abs = os.path.abspath(candidate)
    try:
        return _ensure_within_data_dir(candidate_abs)
    except ValueError:
        # If not, candidate is relative to DATA_DIR, so append it under DATA_DIR.
        safe_parts: list[str] = []
        for part in re.split(r"[\\/]+", candidate):
            if not part:
                continue
            safe_part = _sanitize_path_component(part)
            if not safe_part:
                raise ValueError("Invalid target directory.") from None
            safe_parts.append(safe_part)
        if not safe_parts:
            raise ValueError("Invalid target directory.") from None
        return _safe_data_path(*safe_parts)


def _write_binary_file(filepath: str, payload: bytes) -> None:
    """Persist bytes to a validated DATA_DIR file path."""
    if ".." in filepath:
        raise ValueError("Path traversal detected")
    filename = os.path.basename(filepath)
    if not re.match(r"^[A-Za-z0-9._-]+$", filename):
        raise ValueError("Invalid filename pattern")

    safe_filepath = _ensure_within_data_dir(filepath)
    parent_dir = os.path.dirname(safe_filepath)
    if not parent_dir:
        raise ValueError("Invalid filepath: missing parent directory.")
    safe_parent_dir = _ensure_within_data_dir(parent_dir)
    safe_filename = sanitize_relative_segment(os.path.basename(safe_filepath))
    if not safe_filename:
        raise ValueError("Invalid filepath: invalid filename.")
    safe_filepath = ensure_within_base_dir(
        os.path.join(safe_parent_dir, safe_filename), safe_parent_dir
    )
    # Re-verify containment at the sink so the taint analysis trusts the path.
    data_root = os.path.realpath(settings.DATA_DIR)
    if os.path.commonpath([os.path.realpath(safe_filepath), data_root]) != data_root:
        raise ValueError("Invalid filepath: escapes DATA_DIR.")
    os.makedirs(safe_parent_dir, exist_ok=True)
    with open(safe_filepath, "wb") as file_handle:
        file_handle.write(payload)


def _build_output_filepath(target_dir: str, filename: Optional[str], extension: str) -> str:
    """Build a validated output file path inside DATA_DIR."""
    resolved_dir = _ensure_within_data_dir(target_dir)
    os.makedirs(resolved_dir, exist_ok=True)
    safe_filename = _normalize_output_filename(filename, extension)
    return _ensure_within_data_dir(os.path.join(resolved_dir, safe_filename))


def _redact_url_for_logs(url: str) -> str:
    """Redact URL query/fragment so signed tokens are not logged."""
    try:
        parts = urlsplit(url or "")
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    except ValueError:
        return "<invalid-url>"


def _safe_prompt_summary(prompt: str) -> str:
    """Return a non-sensitive summary of a prompt for logging."""
    return f"len={len(prompt or '')}"


def _sanitize_generation_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Return generation kwargs safe for logs."""
    sanitized = dict(kwargs)
    if "api_key" in sanitized:
        sanitized["api_key"] = "<redacted>"
    if "prompt" in sanitized:
        sanitized["prompt"] = _safe_prompt_summary(str(sanitized.get("prompt") or ""))
    if "messages" in sanitized:
        sanitized["messages"] = "<redacted>"
    return sanitized


class MediaEngine:
    @staticmethod
    def _resolve_sd_dimensions(target_type: str, min_long_edge: Optional[int]) -> tuple[int, int]:
        edge = min_long_edge or 1024
        if edge <= 0:
            edge = 1024

        t_type = (target_type or "").upper()

        def round_to_8(val: float) -> int:
            return int(round(val / 8.0) * 8)

        if t_type == "COVER":
            return round_to_8(edge), round_to_8(edge / 2.0)
        elif t_type == "SCENE":
            return round_to_8(edge), round_to_8(edge * 9.0 / 16.0)
        elif t_type in ("NPC", "PROTAGONIST", "CHARACTER"):
            return round_to_8(edge * 4.0 / 5.0), round_to_8(edge)
        else:
            # OBJECT, ITEM, etc.
            return round_to_8(edge), round_to_8(edge)

    @staticmethod
    async def _copy_static_svg_placeholder(
        target_dir: str,
        entity_id: str,
        category: str,
        filename: Optional[str] = None,
    ) -> Optional[str]:
        from backend.engine.media_file_operations import _copy_static_svg_placeholder

        return await run_file_operation(
            _copy_static_svg_placeholder, target_dir, entity_id, category, filename
        )

    @staticmethod
    async def cleanup_adventure_assets(adventure_id: str) -> None:
        from backend.engine.media_file_operations import cleanup_adventure_assets

        return await run_file_operation(cleanup_adventure_assets, adventure_id)

    @staticmethod
    async def _generate_thumbnail(filepath: str, max_size: int = 480) -> str | None:
        from backend.engine.media_file_operations import _generate_thumbnail

        return await run_file_operation(_generate_thumbnail, filepath, max_size)

    @staticmethod
    async def ensure_thumbnails(adventure_id: str) -> None:
        """Scans the library for an adventure and ensures all images have thumbnails."""
        target_dir = _safe_data_path("adventures", "library", adventure_id)
        paths = await run_file_operation(list_thumbnail_sources, target_dir)
        tasks = [MediaEngine._generate_thumbnail(path) for path in paths]

        if tasks:
            logger.info(
                "Checking thumbnails for %d existing images in adventure %s (local resize, no image model)",
                len(tasks),
                adventure_id,
            )
            results = await asyncio.gather(*tasks)
            available = sum(result is not None for result in results)
            logger.info(
                "Thumbnail check complete for adventure %s: %d available, %d failed",
                adventure_id,
                available,
                len(results) - available,
            )

    @classmethod
    def _get_litellm(cls) -> Any:
        return litellm

    @staticmethod
    def _sanitize_prompt(prompt: str) -> str:
        """Reject ambiguous unsupported input rather than silently changing its meaning."""
        if re.search(r"\braping\b", prompt, flags=re.IGNORECASE):
            raise ValueError(
                "The image description contains an unsupported term. Revise the description before generating."
            )
        return prompt

    @staticmethod
    def _apply_no_text_instruction(prompt: str) -> str:
        """Append a global no-text instruction to image prompts when missing."""
        prompt = prompt.strip()
        # Remove trailing dots to avoid double dots when appending suffix
        while prompt.endswith("."):
            prompt = prompt[:-1].strip()

        normalized = MediaEngine._sanitize_prompt(prompt)
        if prompts.NO_TEXT_IMAGE_PROMPT_SUFFIX.lower() in normalized.lower():
            return normalized
        # Combine instructions for better enforcement
        return f"{normalized}. {prompts.NO_TEXT_IMAGE_PROMPT_SUFFIX}"

    @staticmethod
    def _normalize_black_forest_labs_model(model: str) -> str:
        """Return a BFL model slug suitable for the direct API.

        If the saved model is still an OpenAI-style default, fall back to a valid
        BFL FLUX model so older settings do not silently generate nothing.
        """
        normalized = (model or "").strip()
        if not normalized:
            return BFL_DEFAULT_MODEL

        lowered = normalized.lower()
        if lowered.startswith(("openai/", "dall-e", "openrouter/", "google/", "gemini/")):
            return BFL_DEFAULT_MODEL.removeprefix("black_forest_labs/")

        normalized = normalized.removeprefix("black_forest_labs/")
        return resolve_bfl_model_alias(normalized)

    @staticmethod
    async def _generate_image_black_forest_labs_direct(
        prompt: str,
        model: str,
        api_key: str,
        target_dir: str,
        filename: Optional[str] = None,
        provider_options: Optional[dict[str, Any]] = None,
    ) -> Optional[str]:
        from backend.engine.media_bfl import _generate_image_black_forest_labs_direct

        return await _generate_image_black_forest_labs_direct(
            MediaEngine,
            prompt=prompt,
            model=model,
            api_key=api_key,
            target_dir=target_dir,
            filename=filename,
            provider_options=provider_options,
        )

    @staticmethod
    async def _generate_image_openrouter_direct(
        prompt: str,
        model: str,
        api_key: Optional[str],
        target_dir: str,
        filename: Optional[str] = None,
        provider_options: Optional[dict[str, Any]] = None,
    ) -> Optional[str]:
        from backend.engine.media_openrouter import _generate_image_openrouter_direct

        return await _generate_image_openrouter_direct(
            MediaEngine,
            prompt=prompt,
            model=model,
            api_key=api_key,
            target_dir=target_dir,
            filename=filename,
            provider_options=provider_options,
        )

    @staticmethod
    async def _generate_image_openrouter_chat_fallback(
        prompt: str,
        model: str,
        api_key: Optional[str],
        target_dir: str,
        filename: Optional[str] = None,
        provider_options: Optional[dict[str, Any]] = None,
    ) -> Optional[str]:
        from backend.engine.media_openrouter import _generate_image_openrouter_chat_fallback

        return await _generate_image_openrouter_chat_fallback(
            MediaEngine,
            prompt=prompt,
            model=model,
            api_key=api_key,
            target_dir=target_dir,
            filename=filename,
            provider_options=provider_options,
        )

    @staticmethod
    def _resolve_api_key(provider: str, api_keys_dict: dict) -> Optional[str]:
        """Resolves API key by checking environment variables first, then the provided dictionary."""
        provider_key = (provider or "").lower()

        # 1. Check environment variables first
        env_key = settings.get_env_api_key(provider_key)
        if env_key:
            return env_key

        # 2. Fallback to database-stored (and encrypted) keys
        if api_keys_dict and provider_key in api_keys_dict:
            try:
                return encryption_util.decrypt_key(api_keys_dict[provider_key])
            except (ValueError, TypeError, KeyError):
                logger.error("Failed to decrypt API key for provider '%s'", provider_key)
                return None

        return None

    @staticmethod
    @async_operation("image")
    async def generate_image(
        prompt: str,
        model: str | None,
        api_key: Optional[str],
        provider: str = "openai",
        adventure_id: Optional[str] = None,
        target_dir: Optional[str] = None,
        filename: Optional[str] = None,
        provider_options: Optional[dict[str, Any]] = None,
        style_instruction: Optional[str] = None,
    ) -> Optional[str]:
        from backend.engine.media_generation import generate_image

        return await generate_image(
            MediaEngine,
            prompt=prompt,
            model=model,
            api_key=api_key,
            provider=provider,
            adventure_id=adventure_id,
            target_dir=target_dir,
            filename=filename,
            provider_options=provider_options,
            style_instruction=style_instruction,
        )

    @staticmethod
    def _extract_image_payload(response: Any) -> tuple[Optional[str], Optional[str]]:
        """Extract URL or base64 image payload from provider responses."""
        if not response:
            return None, None

        data = getattr(response, "data", None)
        if isinstance(data, list) and data:
            image_data = data[0]
            image_url = getattr(image_data, "url", None)
            b64_json = getattr(image_data, "b64_json", None)

            if image_url and image_url.startswith("data:image/"):
                b64_json = image_url
                image_url = None

            if image_url or b64_json:
                return image_url, b64_json

            if isinstance(image_data, dict):
                url = image_data.get("url")
                b64 = image_data.get("b64_json")
                if url and url.startswith("data:image/"):
                    return None, url
                return url, b64

        if isinstance(response, dict):
            return _extract_mapping_image_payload(response)

        return None, None

    @staticmethod
    async def _generate_image_ollama_direct(
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
        from backend.engine.media_local_images import _generate_image_ollama_direct

        return await _generate_image_ollama_direct(
            MediaEngine,
            prompt=prompt,
            model=model,
            ollama_url=ollama_url,
            target_dir=target_dir,
            filename=filename,
            width=width,
            height=height,
            steps=steps,
            seed=seed,
            negative_prompt=negative_prompt,
        )

    @staticmethod
    async def _generate_image_stable_diffusion_direct(
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
        from backend.engine.media_local_images import _generate_image_stable_diffusion_direct

        return await _generate_image_stable_diffusion_direct(
            MediaEngine,
            prompt=prompt,
            model=model,
            stable_diffusion_url=stable_diffusion_url,
            target_dir=target_dir,
            filename=filename,
            width=width,
            height=height,
            steps=steps,
            cfg_scale=cfg_scale,
            seed=seed,
            negative_prompt=negative_prompt,
            image_format=image_format,
            image_quality=image_quality,
            sampler_name=sampler_name,
            scheduler=scheduler,
        )

    @staticmethod
    async def _save_b64_image(
        b64_data: str,
        target_dir: str,
        filename: Optional[str] = None,
        image_format: str = "jpeg",
        quality: int = 85,
    ) -> Optional[str]:
        """Decodes and saves a base64 image string."""
        try:
            safe_target_dir = _resolve_output_dir(target_dir)
            ext = "jpg" if image_format.lower() == "jpeg" else "png"
            filepath = await run_file_operation(
                _build_output_filepath, safe_target_dir, filename, ext
            )

            image_bytes = await run_file_operation(decode_image_payload, b64_data)
            await run_file_operation(
                persist_image_bytes, filepath, image_bytes, image_format, quality
            )

            # Generate thumbnail
            await MediaEngine._generate_thumbnail(filepath)

            return local_path_to_data_url(filepath)
        except (ValueError, OSError, TypeError):
            logger.exception("Error saving b64 image")
            return None

    @staticmethod
    async def _save_remote_image(
        url: str,
        target_dir: str,
        filename: Optional[str] = None,
        image_format: str = "jpeg",
        quality: int = 85,
    ) -> Optional[str]:
        """Downloads a remote image and persists it in the specified directory."""
        try:
            from backend.engine.image_download import download_image

            content = await asyncio.to_thread(download_image, url)
            safe_target_dir = _resolve_output_dir(target_dir)
            ext = "jpg" if image_format.lower() == "jpeg" else "png"
            filepath = await run_file_operation(
                _build_output_filepath, safe_target_dir, filename, ext
            )
            await run_file_operation(persist_image_bytes, filepath, content, image_format, quality)
            await MediaEngine._generate_thumbnail(filepath)
            return local_path_to_data_url(filepath)

        except (requests.RequestException, OSError, ValueError):
            logger.exception("Error saving remote image")
            return None

    @staticmethod
    async def generate_scene_image(
        prompt: str,
        adventure_id: str,
        user_config: dict,
        api_keys: dict,
        style_instruction: Optional[str] = None,
        use_advanced_model: bool = True,
    ) -> Optional[str]:
        """High-level wrapper for gameplay scene generation (uses Advanced Model by default)."""
        t2i = user_config.get("t2i_settings")
        if not t2i:
            logger.warning("No T2I settings found in user_config")
            return None

        if use_advanced_model:
            provider = (t2i.get("advanced_model_provider") or t2i.get("provider", "openai")).lower()
            model = t2i.get("advanced_model")
        else:
            provider = (t2i.get("simple_model_provider") or t2i.get("provider", "openai")).lower()
            model = t2i.get("simple_model")

        provider = image_provider(t2i, "advanced" if use_advanced_model else "simple", "background")

        logger.info("Resolving scene generation: provider=%s, model=%s", provider, model)

        if not model and provider != "comfyui":
            raise ValueError("Missing image model configuration for scenes.")

        api_key = MediaEngine._resolve_api_key(provider, api_keys)
        if provider not in ("ollama", "stable_diffusion", "comfyui") and not api_key:
            logger.error(
                "API key resolution failed for provider: %s (Advanced Model/Scenes)", provider
            )
            raise ValueError(
                f"Missing image configuration or API key for {provider} (Advanced Model). Please check your Visual Preferences in Admin settings."
            )

        target_dir = _safe_data_path("adventures", "library", adventure_id, "scenes")
        ext = "jpg" if (t2i.get("image_format") or "jpeg").lower() == "jpeg" else "png"

        # Use adventure_id as prefix for clarity
        safe_id = slugify(adventure_id)
        filename = f"{safe_id}_scene_{uuid.uuid4().hex[:8]}.{ext}"

        # Resolve steps and cfg_scale for simple or advanced model
        options = dict(t2i)
        options["image_purpose"] = "background"
        options["visual_target_type"] = "scene"
        options["_prompt_user"] = user_config.get("prompt_user")
        options["comfyui_profile"] = "advanced" if use_advanced_model else "simple"
        if use_advanced_model:
            options["steps"] = t2i.get("advanced_steps")
            options["cfg_scale"] = t2i.get("advanced_cfg_scale")
            options["sampler_name"] = t2i.get("advanced_sampler_name")
            options["scheduler"] = t2i.get("advanced_scheduler")
            min_long_edge = t2i.get("advanced_min_long_edge")
        else:
            options["steps"] = t2i.get("simple_steps")
            options["cfg_scale"] = t2i.get("simple_cfg_scale")
            options["sampler_name"] = t2i.get("simple_sampler_name")
            options["scheduler"] = t2i.get("simple_scheduler")
            min_long_edge = t2i.get("simple_min_long_edge")

        if provider in ("stable_diffusion", "ollama", "comfyui"):
            width, height = MediaEngine._resolve_sd_dimensions("SCENE", min_long_edge)
            options["width"] = width
            options["height"] = height

        return await MediaEngine.generate_image(
            prompt=prompt,
            model=model,
            api_key=api_key,
            provider=provider,
            adventure_id=adventure_id,
            target_dir=target_dir,
            filename=filename,
            provider_options=options,
            style_instruction=style_instruction,
        )

    @staticmethod
    async def generate_entity_image(
        prompt: str,
        adventure_id: str,
        entity_id: str,
        entity_type: str,
        user_config: dict,
        api_keys: dict,
        style_instruction: Optional[str] = None,
        use_advanced_model: bool = False,
    ) -> Optional[str]:
        """High-level wrapper for NPC/Object generation (uses Simple Model by default)."""
        t2i = user_config.get("t2i_settings")
        if not t2i:
            logger.warning("No T2I settings found in user_config")
            return None

        if use_advanced_model:
            provider = (t2i.get("advanced_model_provider") or t2i.get("provider", "openai")).lower()
            model = t2i.get("advanced_model")
        else:
            provider = (t2i.get("simple_model_provider") or t2i.get("provider", "openai")).lower()
            model = t2i.get("simple_model")

        provider = image_provider(
            t2i, "advanced" if use_advanced_model else "simple", purpose_for(entity_type)
        )

        logger.info("Resolving entity generation: provider=%s, model=%s", provider, model)

        if not model and provider != "comfyui":
            raise ValueError("Missing image model configuration for entities.")

        api_key = MediaEngine._resolve_api_key(provider, api_keys)
        if provider not in ("ollama", "stable_diffusion", "comfyui") and not api_key:
            logger.error(
                "API key resolution failed for provider: %s (Simple Model/Entities)", provider
            )
            raise ValueError(
                f"Missing image configuration or API key for {provider} (Simple Model). Please check your Visual Preferences in Admin settings."
            )

        target_dir = _safe_data_path("adventures", "library", adventure_id, "entities")
        ext = "jpg" if (t2i.get("image_format") or "jpeg").lower() == "jpeg" else "png"

        # Use adventure_id and entity_id as prefix for clarity
        safe_adv_id = slugify(adventure_id)
        safe_ent_id = slugify(entity_id)
        filename = f"{safe_adv_id}_{safe_ent_id}_{uuid.uuid4().hex[:8]}.{ext}"

        # Resolve steps and cfg_scale for simple or advanced model
        options = dict(t2i)
        options["image_purpose"] = purpose_for(entity_type)
        options["visual_target_type"] = entity_type.lower()
        options["_prompt_user"] = user_config.get("prompt_user")
        options["comfyui_profile"] = "advanced" if use_advanced_model else "simple"
        if use_advanced_model:
            options["steps"] = t2i.get("advanced_steps")
            options["cfg_scale"] = t2i.get("advanced_cfg_scale")
            options["sampler_name"] = t2i.get("advanced_sampler_name")
            options["scheduler"] = t2i.get("advanced_scheduler")
            min_long_edge = t2i.get("advanced_min_long_edge")
        else:
            options["steps"] = t2i.get("simple_steps")
            options["cfg_scale"] = t2i.get("simple_cfg_scale")
            options["sampler_name"] = t2i.get("simple_sampler_name")
            options["scheduler"] = t2i.get("simple_scheduler")
            min_long_edge = t2i.get("simple_min_long_edge")

        if provider in ("stable_diffusion", "ollama", "comfyui"):
            width, height = MediaEngine._resolve_sd_dimensions(entity_type, min_long_edge)
            options["width"] = width
            options["height"] = height

        return await MediaEngine.generate_image(
            prompt=prompt,
            model=model,
            api_key=api_key,
            provider=provider,
            adventure_id=adventure_id,
            target_dir=target_dir,
            filename=filename,
            provider_options=options,
            style_instruction=style_instruction,
        )

    @staticmethod
    async def generate_adventure_cover(
        title: str,
        original_prompt: str,
        adventure_id: str,
        user_config: dict,
        api_keys: dict,
        style_instruction: Optional[str] = None,
        use_advanced_model: bool = True,
    ) -> Optional[str]:
        """High-level wrapper for adventure cover generation (uses Advanced Model, 3:2 aspect ratio)."""
        t2i = user_config.get("t2i_settings")
        if not t2i:
            logger.warning("No T2I settings found in user_config")
            return None

        profile = "advanced" if use_advanced_model else "simple"
        provider = (t2i.get(f"{profile}_model_provider") or t2i.get("provider", "openai")).lower()
        model = t2i.get(f"{profile}_model")

        provider = image_provider(t2i, "advanced" if use_advanced_model else "simple", "cover")

        logger.info("Resolving adventure cover generation: provider=%s, model=%s", provider, model)

        if not model and provider != "comfyui":
            raise ValueError("Missing image model configuration for adventure cover.")

        api_key = MediaEngine._resolve_api_key(provider, api_keys)
        if provider not in ("ollama", "stable_diffusion", "comfyui") and not api_key:
            logger.error(
                "API key resolution failed for provider: %s (Advanced Model/Cover)", provider
            )
            raise ValueError(
                f"Missing image configuration or API key for {provider} (Advanced Model/Cover). Please check your Visual Preferences in Admin settings."
            )

        safe_adventure_id = _sanitize_path_component(adventure_id)
        if not safe_adventure_id:
            raise ValueError("Invalid adventure identifier.")

        target_dir = _safe_data_path("adventures", "library", safe_adventure_id)
        ext = "jpg" if (t2i.get("image_format") or "jpeg").lower() == "jpeg" else "png"

        # Use sanitized adventure_id as prefix for clarity
        safe_id = safe_adventure_id
        filename = f"{safe_id}_cover_{uuid.uuid4().hex[:8]}.{ext}"

        prompt = cover_source(
            title,
            original_prompt,
            provider,
            {**t2i, "comfyui_profile": profile, "image_purpose": "cover"},
        )

        # Resolve steps and cfg_scale for advanced model
        options = dict(t2i)
        options["image_purpose"] = "cover"
        options["visual_target_type"] = "cover"
        options["_prompt_user"] = user_config.get("prompt_user")
        options["comfyui_profile"] = profile
        options.setdefault("aspect_ratio", "3:2")
        existing_neg = options.get("negative_prompt") or ""
        anti_split_neg = "split screen, multi-panel, panels, comic strip, collage, triptych, diptych, multiple views, storyboard, frames, borders, dividers"
        options["negative_prompt"] = (
            f"{existing_neg}, {anti_split_neg}".strip(", ") if existing_neg else anti_split_neg
        )
        options["steps"] = t2i.get(f"{profile}_steps")
        options["cfg_scale"] = t2i.get(f"{profile}_cfg_scale")
        options["sampler_name"] = t2i.get(f"{profile}_sampler_name")
        options["scheduler"] = t2i.get(f"{profile}_scheduler")
        min_long_edge = t2i.get(f"{profile}_min_long_edge")

        if provider in ("stable_diffusion", "ollama", "comfyui"):
            width, height = MediaEngine._resolve_sd_dimensions("COVER", min_long_edge)
            options["width"] = width
            options["height"] = height

        return await MediaEngine.generate_image(
            prompt=prompt,
            model=model,
            api_key=api_key,
            provider=provider,
            adventure_id=adventure_id,
            target_dir=target_dir,
            filename=filename,
            provider_options=options,
            style_instruction=style_instruction,
        )

    @staticmethod
    async def generate_placeholder(
        adventure_id: str,
        entity_id: str,
        target_dir: str,
        filename: Optional[str] = None,
        category: str = "",
        theme: Optional[str] = None,
    ) -> str:
        from backend.engine.media_placeholders import generate_placeholder

        return await generate_placeholder(
            MediaEngine,
            adventure_id=adventure_id,
            entity_id=entity_id,
            target_dir=target_dir,
            filename=filename,
            category=category,
            theme=theme,
        )

    @staticmethod
    async def generate_svg_placeholder(
        adventure_id: str,
        entity_id: str,
        target_dir: str,
        filename: Optional[str] = "placeholder.svg",
        category: str = "",
    ) -> str:
        from backend.engine.media_file_operations import generate_svg_placeholder

        return await run_file_operation(
            generate_svg_placeholder, adventure_id, entity_id, target_dir, filename, category
        )


def _extract_mapping_image_payload(response: dict[str, Any]) -> tuple[str | None, str | None]:
    images = response.get("images")
    if isinstance(images, list) and images:
        first = images[0]
        if isinstance(first, str):
            return None, first
    return response.get("url"), response.get("b64_json")
