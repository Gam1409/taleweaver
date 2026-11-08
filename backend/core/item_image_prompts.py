"""Item composition belongs to the image task, independently of model/style presets."""

from typing import Any

from backend.core.image_purposes import purpose_for

ITEM_COMPOSITION = (
    "Object-only product still life. Show only the requested item(s), fully visible, "
    "arranged directly on a suitable surface or background. "
    "For clothing, show the empty garment unworn and laid flat. "
    "No people, human body parts, live animals or other living creatures. "
    "No wearers, holders, mannequins, clothes hangers or hanging racks."
)
ITEM_ADAPTER_INSTRUCTION = (
    ITEM_COMPOSITION
    + " For clothing, describe the empty garment itself, not its owner wearing it; "
    "it must be unworn and laid flat, without a body, mannequin or hangers. "
    "Owner names establish ownership only and must not become subjects. "
    "Preserve the item's stated count, materials, cut, proportions and decorative motifs; "
    "a matching pair remains a pair. Avoid labels and UI frames unless explicitly requested."
)
ITEM_NEGATIVE = (
    "people, person, human, human body, face, hands, wearer, holder, animal, living creature, "
    "mannequin, clothes hanger, coat hanger, hanger, clothing rack"
)


def item_purpose(options: dict[str, Any] | None) -> str:
    options = options or {}
    return purpose_for(str(options.get("image_purpose") or options.get("visual_target_type") or ""))


def _append_once(text: str, instruction: str, separator: str) -> str:
    return (
        text
        if instruction.rstrip(".").casefold() in text.casefold()
        else separator.join(part for part in (text.strip(), instruction) if part)
    )


def item_composition(prompt: str, purpose: str | None) -> str:
    return (
        _append_once(prompt, ITEM_COMPOSITION, " ")
        if purpose_for(purpose or "") == "object"
        else prompt
    )


def item_negative(prompt: str, purpose: str | None) -> str:
    return (
        _append_once(prompt, ITEM_NEGATIVE, ", ")
        if purpose_for(purpose or "") == "object"
        else prompt
    )


def item_provider_options(options: dict[str, Any] | None, provider: str) -> dict[str, Any] | None:
    if (
        provider not in {"stable_diffusion", "ollama", "comfyui"}
        or item_purpose(options) != "object"
    ):
        return options
    result = dict(options or {})
    result["negative_prompt"] = item_negative(str(result.get("negative_prompt") or ""), "object")
    return result
