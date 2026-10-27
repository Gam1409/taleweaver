"""Black Forest Labs submission and polling."""

import asyncio
import logging
import time
from typing import Any, Optional

import requests

from backend.core.config import settings
from backend.engine.bfl_payloads import build_bfl_payload

logger = logging.getLogger(__name__)


async def _generate_image_black_forest_labs_direct(
    engine,
    prompt: str,
    model: str,
    api_key: str,
    target_dir: str,
    filename: Optional[str] = None,
    provider_options: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """Generate a BFL image by calling the REST API directly and polling for completion."""
    from backend.engine.media_engine import BFL_API_BASE, _safe_prompt_summary

    provider_options = provider_options or {}
    model_slug = engine._normalize_black_forest_labs_model(model)
    endpoint = f"{BFL_API_BASE}/{model_slug}"

    payload = build_bfl_payload(model_slug, prompt, provider_options)
    logger.info("BFL submission payload prepared (prompt_%s)", _safe_prompt_summary(prompt))

    response = await asyncio.to_thread(
        requests.post,
        endpoint,
        headers={"Content-Type": "application/json", "x-key": api_key},
        json=payload,
        timeout=settings.VISUAL_TIMEOUT,
    )
    if response.status_code != 200:
        logger.error("BFL image generation submit failed. status=%s", response.status_code)
        return None

    body = response.json()
    polling_url = body.get("polling_url")
    if not polling_url:
        logger.error("BFL response did not include polling_url")
        return None

    return await _poll_bfl_result(engine, polling_url, api_key, target_dir, filename)


async def _poll_bfl_result(engine, polling_url, api_key, target_dir, filename):
    poll_deadline = time.monotonic() + 600.0
    while time.monotonic() < poll_deadline:
        poll_response = await asyncio.to_thread(
            requests.get,
            polling_url,
            headers={"accept": "application/json", "x-key": api_key},
            timeout=max(30, settings.VISUAL_TIMEOUT),
        )
        if poll_response.status_code != 200:
            logger.error(
                "BFL polling failed. status=%s",
                poll_response.status_code,
            )
            return None

        poll_body = poll_response.json()
        status = str(poll_body.get("status") or "").lower()
        logger.info("BFL polling status: %s", status)
        if status == "ready":
            result = poll_body.get("result") or {}
            sample_url = result.get("sample")
            if not sample_url:
                logger.error("BFL polling response missing result.sample")
                return None
            return await engine._save_remote_image(sample_url, target_dir, filename)

        if "moderated" in status:
            logger.warning("BFL generation moderated")
            raise ValueError(f"BFL Image Generation blocked by safety filter: {status}")

        if status in {"error", "failed", "expired", "task not found", "tasknotfound"}:
            logger.error("BFL generation failed, expired or not found")
            return None

        await asyncio.sleep(2.0)

    logger.error("BFL polling timed out after 600s")
    return None
