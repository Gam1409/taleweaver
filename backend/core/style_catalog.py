from typing import Any, Optional

from backend.core.catalog_defaults import DEFAULT_IMAGE_STYLES, DEFAULT_TONES

_ANIME_ID = "shonen-anime"  # Stable ID and artwork path preserve saved selections.
_LEGACY_ANIME_FIELDS = {
    "name": "Modern Shonen Anime",
    "description": "Sharp lines, dynamic digital lighting, and high-energy animation style.",
    "instruction": "Modern shonen anime style, crisp line art, dynamic cinematic lighting, vibrant cel-shading, high-octane energy, digital animation aesthetic, sharp focus, vivid special effects.",
}


def normalize_image_style(style: dict[str, Any]) -> dict[str, Any]:
    """Refresh unchanged built-in fields in saved copies; preserve authored overrides."""
    result = dict(style)
    if style.get("id") != _ANIME_ID and style.get("name") != _LEGACY_ANIME_FIELDS["name"]:
        return result
    current = next(item for item in DEFAULT_IMAGE_STYLES if item["id"] == _ANIME_ID)
    for field, legacy in _LEGACY_ANIME_FIELDS.items():
        if result.get(field) == legacy:
            result[field] = current[field]
    return result


def normalize_image_styles_catalog(catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [normalize_image_style(item) for item in catalog]


def default_image_styles_catalog() -> list[dict[str, Any]]:
    """Return a copy of default image styles to avoid accidental mutation."""
    return [dict(item) for item in DEFAULT_IMAGE_STYLES]


def default_tones_catalog() -> list[dict[str, Any]]:
    """Return a copy of default tones to avoid accidental mutation."""
    return [dict(item) for item in DEFAULT_TONES]


def resolve_style_instruction(
    selected_image_styles: Optional[list[Any]],
    user_catalog: list[dict[str, Any]] | None,
) -> str:
    """Resolve style instruction from selected style, then user catalog, then default catalog."""
    if not selected_image_styles:
        return ""

    first_style = selected_image_styles[0]
    style_id = None

    if isinstance(first_style, dict):
        first_style = normalize_image_style(first_style)
        direct_instruction = (first_style.get("instruction") or "").strip()
        if direct_instruction:
            return direct_instruction
        style_id = first_style.get("id") or first_style.get("name")
    elif isinstance(first_style, str):
        style_id = first_style

    if not style_id:
        return ""
    if style_id == _LEGACY_ANIME_FIELDS["name"]:
        style_id = _ANIME_ID

    for catalog in (user_catalog or [], default_image_styles_catalog()):
        for raw_entry in catalog:
            entry = normalize_image_style(raw_entry)
            if entry.get("id") == style_id or entry.get("name") == style_id:
                return (entry.get("instruction") or "").strip()

    return str(style_id)


def resolve_tone_instruction(
    selected_tone: Optional[str | dict[str, Any]],
    user_catalog: list[dict[str, Any]] | None,
) -> str:
    """Resolve tone instruction from selected tone, then user catalog, then default catalog."""
    if not selected_tone:
        return ""

    tone_id = None

    if isinstance(selected_tone, dict):
        direct_instruction = (selected_tone.get("instruction") or "").strip()
        if direct_instruction:
            return direct_instruction
        tone_id = selected_tone.get("id") or selected_tone.get("name")
    elif isinstance(selected_tone, str):
        tone_id = selected_tone

    if not tone_id:
        return ""

    for catalog in (user_catalog or [], default_tones_catalog()):
        for entry in catalog:
            if entry.get("id") == tone_id or entry.get("name") == tone_id:
                return (entry.get("instruction") or "").strip()

    return tone_id
