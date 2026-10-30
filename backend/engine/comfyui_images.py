"""Prepare local references and persist ComfyUI outputs via TaleWeaver storage."""

import asyncio
import io
import secrets
from pathlib import Path

from PIL import Image

from backend.core.comfyui_config import ComfySettings, select_workflow
from backend.core.visual_trace import record
from backend.engine.comfyui_client import ComfyClient
from backend.engine.comfyui_output import bounded_dimensions, prepare_generated_image
from backend.engine.image_prompt_adapter import prepare_prompt
from backend.engine.visual_progress import report
from backend.utils.path_security import (
    data_url_to_local_path,
    ensure_within_data_dir,
    local_path_to_data_url,
)


def reference_png(url: str) -> bytes:
    path = data_url_to_local_path(url)
    if not path:
        raise ValueError("The reference must be a local TaleWeaver image.")
    safe_path = ensure_within_data_dir(path)
    try:
        if Path(safe_path).stat().st_size > 16 * 1024 * 1024:
            raise ValueError("Reference image exceeds 16 MiB.")
        with Image.open(safe_path) as image:
            if image.width * image.height > 16777216:
                raise ValueError("Reference image exceeds 16 megapixels.")
            output = io.BytesIO()
            image.convert("RGBA").save(output, "PNG")
            return output.getvalue()
    except OSError as exc:
        raise ValueError(
            "Reference is missing, unreadable, or a placeholder. Upload a raster image first."
        ) from exc


async def generate_comfy_image(
    prompt: str, options: dict, target_dir: str, filename: str | None
) -> str:
    from backend.engine.media_engine import (
        MediaEngine,
        _build_output_filepath,
        _resolve_output_dir,
        _write_binary_file,
    )

    settings = ComfySettings.model_validate(options)
    reference = options.get("reference_image_url")
    workflow = select_workflow(options, reference=bool(reference))
    prepared_prompt = await prepare_prompt(prompt, options)
    render_options = dict(options)
    if options.get("width") is None and options.get("height") is None:
        role = options.get("comfyui_profile", "simple")
        width, height = MediaEngine._resolve_sd_dimensions(
            options.get("visual_target_type") or "object", options.get(f"{role}_min_long_edge")
        )
        render_options.update(width=width, height=height)
    values = {
        **bounded_dimensions(render_options, workflow.dimension_multiple),
        "negative_prompt": prepared_prompt["negative"],
    }
    values["prompt"] = prepared_prompt["positive"]
    seed = options.get("seed")
    values["seed"] = seed if isinstance(seed, int) and seed >= 0 else secrets.randbits(48)
    async with ComfyClient(settings.comfyui_url) as client:
        if reference:
            values["image"] = await client.upload(await asyncio.to_thread(reference_png, reference))
        graph = workflow.render(values)
        record(
            "comfy.mapped_inputs",
            inputs={
                name: graph[binding.node_id]["inputs"][binding.input_name]
                for name, binding in workflow.bindings.items()
                if name in {"prompt", "negative_prompt", "width", "height", "seed"}
            },
        )
        details = options.get("_generation_details")
        if isinstance(details, dict):
            details.update(provider="comfyui", workflow=workflow.name)
            # Capture only mapped inputs, never the graph, URLs or credentials.
            for name, binding in workflow.bindings.items():
                if name == "image":
                    continue
                key = "positive_prompt" if name == "prompt" else name
                details[key] = graph[binding.node_id]["inputs"][binding.input_name]
        try:
            data = await asyncio.wait_for(
                client.execute(graph, workflow.output_node, settings.comfyui_timeout),
                timeout=settings.comfyui_timeout,
            )
        except TimeoutError as exc:
            raise TimeoutError(
                f"ComfyUI generation timed out (limit: {settings.comfyui_timeout}s). "
                "A running remote job may continue."
            ) from exc
    image_format = options.get("image_format") or "png"
    prepared = await asyncio.to_thread(
        prepare_generated_image,
        data,
        options.get("visual_target_type"),
        image_format,
        options.get("image_quality") or 85,
    )
    extension = "jpg" if image_format.lower() in ("jpeg", "jpg") else "png"
    filepath = _build_output_filepath(_resolve_output_dir(target_dir), filename, extension)
    report("saving")
    await asyncio.to_thread(_write_binary_file, filepath, prepared)
    await MediaEngine._generate_thumbnail(filepath)
    return local_path_to_data_url(filepath)
