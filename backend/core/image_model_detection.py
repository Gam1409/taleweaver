"""Conservative filename hints from base-model loader nodes; no weight inspection."""

import re

PATTERNS = (
    ("anima", r"(?:^|[._ -])anima(?:[._ -]|$)|prefectanima"),
    ("animagine4", r"animagine[^/]*?(?:xl[^/]*?)?4(?:[._ -]|$)"),
    ("pony6", r"pony[^/]*?(?:v6|6xl|6_xl)"),
    ("illustrious", r"illustrious"),
    ("flux1", r"flux[._ -]?1(?:[._ -]|$)"),
    ("sd35", r"(?:sd|stable[._ -]?diffusion)[._ -]?3[._ -]?5"),
    ("qwen_image", r"qwen[._ -]?image(?![^/]*edit)"),
    ("sd15", r"(?:sd[._ -]?1[._ -]?5|v1[._ -]?5[._ -]?pruned)"),
    ("sdxl", r"(?:sd[._ -]?xl[._ -]?base|stable[._ -]?diffusion[._ -]?xl)"),
)
MODEL_INPUTS = {"ckpt_name", "unet_name", "diffusion_model", "model_name"}


def detect_preset_template(graph: dict, reference_graph: dict | None = None) -> dict:
    result = detect_template(graph)
    if reference_graph is None:
        return result
    reference = detect_template(reference_graph)
    if result["template_id"] and reference["template_id"] == result["template_id"]:
        result["models"] = list(dict.fromkeys(result["models"] + reference["models"]))
        return result
    return {
        "template_id": None,
        "models": list(dict.fromkeys(result["models"] + reference["models"])),
        "message": "The base and reference workflows do not identify the same model family. "
        "Choose shared rules manually, or use separate presets for different prompt rules.",
    }


def detect_template(graph: dict) -> dict:
    names = []
    for node in graph.values():
        node_type = str(node.get("class_type", "")).lower()
        if not any(kind in node_type for kind in ("checkpoint", "unet", "diffusionmodel")):
            continue
        names.extend(
            str(v)
            for k, v in node.get("inputs", {}).items()
            if k in MODEL_INPUTS and isinstance(v, str)
        )
    names = list(dict.fromkeys(names))
    matches = [_match(name) for name in names]
    matched = bool(matches) and None not in matches and len(set(matches)) == 1
    return {
        "template_id": matches[0] if matched else None,
        "models": names,
        "message": "Matched a known filename pattern; verify the exact checkpoint."
        if matched
        else "Could not identify one model family reliably. Choose a prompt template manually.",
    }


def _match(name: str) -> str | None:
    basename = name.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if any(
        word in basename for word in ("kontext", "edit", "fill", "inpaint", "controlnet", "refiner")
    ):
        return None
    found = [key for key, pattern in PATTERNS if re.search(pattern, basename)]
    return found[0] if len(found) == 1 else None
