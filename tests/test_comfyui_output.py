"""ComfyUI output limits apply even when workflows resize their own images."""

import io
import random
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from backend.core.config import settings
from backend.core.visual_limits import VISUAL_LIMITS
from backend.engine.comfyui_client import ComfyClient
from backend.engine.comfyui_images import generate_comfy_image
from backend.engine.comfyui_output import bounded_dimensions, prepare_generated_image
from tests.test_comfyui import comfy_options, fake_comfy, workflow

__all__ = ["comfy_options", "fake_comfy", "workflow"]


def png_bytes(size: tuple[int, int]) -> bytes:
    output = io.BytesIO()
    Image.new("RGBA", size, (25, 40, 50, 100)).save(output, "PNG")
    return output.getvalue()


@pytest.mark.parametrize("kind", list(VISUAL_LIMITS))
def test_each_visual_respects_original_dimensions_without_crop(kind):
    limits = VISUAL_LIMITS[kind]
    original_size = (limits["maxWidth"] * 2, limits["maxHeight"] * 2)
    result = prepare_generated_image(png_bytes(original_size), kind, "png", 85)
    assert len(result) <= limits["maxBytes"]
    with Image.open(io.BytesIO(result)) as image:
        assert image.size == (limits["maxWidth"], limits["maxHeight"])
        assert image.getpixel((0, 0))[3] == 100


@pytest.mark.parametrize("image_format", ["png", "jpeg"])
def test_small_images_are_not_upscaled_and_format_is_honored(image_format):
    result = prepare_generated_image(png_bytes((17, 29)), "npc", image_format, 85)
    with Image.open(io.BytesIO(result)) as image:
        assert image.size == (17, 29)
        assert image.format == image_format.upper()
        assert image.mode == ("RGB" if image_format == "jpeg" else "RGBA")


def test_wide_scene_keeps_aspect_ratio():
    result = prepare_generated_image(png_bytes((3200, 1000)), "scene", "png", 85)
    with Image.open(io.BytesIO(result)) as image:
        assert image.size == (1600, 500)


def test_noisy_png_is_reduced_to_fit_byte_budget():
    image = Image.frombytes("RGB", (1024, 1024), random.Random(42).randbytes(1024 * 1024 * 3))
    source = io.BytesIO()
    image.save(source, "PNG")
    limit = VISUAL_LIMITS["object"]["maxBytes"]
    assert len(source.getvalue()) > limit
    result = prepare_generated_image(source.getvalue(), "object", "png", 85)
    assert len(result) <= limit
    with Image.open(io.BytesIO(result)) as resized:
        assert resized.width == resized.height < 1024


def test_decompression_limit_is_checked_before_loading_pixels():
    with pytest.raises(ValueError, match="16 megapixels"):
        prepare_generated_image(png_bytes((4097, 4096)), "cover", "png", 85)


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        ({}, {}),
        ({"width": 800, "height": 600}, {"width": 800, "height": 600}),
        (
            {"visual_target_type": "scene", "width": 4096, "height": 2304},
            {"width": 1600, "height": 896},
        ),
        ({"visual_target_type": "npc", "height": 4000}, {"height": 1280}),
    ],
)
def test_request_dimensions_are_bounded(options, expected):
    assert bounded_dimensions(options) == expected


@pytest.mark.asyncio
async def test_workflow_without_dimension_bindings_still_saves_bounded_output(
    fake_comfy, comfy_options, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ComfyClient, "execute", AsyncMock(return_value=png_bytes((3200, 1800))))
    comfy_options["visual_target_type"] = "scene"
    url = await generate_comfy_image("landscape", comfy_options, str(tmp_path), "scene.png")
    assert url == "/data/scene.png"
    with Image.open(tmp_path / "scene.png") as image:
        assert image.size == (1600, 900)
    with Image.open(tmp_path / "scene_thumb.png") as thumbnail:
        assert thumbnail.size == (480, 270)
