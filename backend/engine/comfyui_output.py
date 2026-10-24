"""Fit ComfyUI inputs and final images to TaleWeaver's existing asset limits."""

import io

from PIL import Image

from backend.core.visual_limits import visual_limits

MAX_DECODE_PIXELS = 16 * 1024 * 1024


def bounded_dimensions(options: dict, multiple: int = 8) -> dict[str, int]:
    """Limit requested dimensions; only graph inputs explicitly mapped will change."""
    bounds = visual_limits(options.get("visual_target_type"))
    dimensions = {}
    for key in ("width", "height"):
        value = options.get(key)
        if value is None:
            continue
        if not isinstance(value, int) or isinstance(value, bool) or value < 8:
            raise ValueError("ComfyUI image dimensions must be integers of at least 8 pixels.")
        dimensions[key] = value
    scale = min([1.0] + [bounds[f"max{key.title()}"] / value for key, value in dimensions.items()])
    return {
        key: max(multiple, int(value * scale) // multiple * multiple)
        for key, value in dimensions.items()
    }


def prepare_generated_image(
    data: bytes, target_type: str | None, image_format: str, quality: int
) -> bytes:
    """Downsize without cropping/upscaling; enforce the final encoded byte limit."""
    bounds = visual_limits(target_type)
    output_format = "JPEG" if image_format.lower() in ("jpeg", "jpg") else "PNG"
    with Image.open(io.BytesIO(data)) as source:
        if source.width * source.height > MAX_DECODE_PIXELS:
            raise ValueError("Generated image exceeds 16 megapixels.")
        image = source.convert("RGB" if output_format == "JPEG" else "RGBA")
    image.thumbnail((bounds["maxWidth"], bounds["maxHeight"]), Image.Resampling.LANCZOS)
    # High-entropy PNGs can exceed the byte budget even at the allowed dimensions.
    for _ in range(10):
        output = io.BytesIO()
        image.save(output, output_format, quality=quality, optimize=True)
        if output.tell() <= bounds["maxBytes"]:
            return output.getvalue()
        image.thumbnail(
            (max(1, int(image.width * 0.8)), max(1, int(image.height * 0.8))),
            Image.Resampling.LANCZOS,
        )
    raise ValueError("Generated image cannot fit the asset file-size limit.")
