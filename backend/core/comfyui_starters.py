"""Small, editable ComfyUI starter graphs with explicit architecture choices."""

from backend.core.comfyui_config import ComfyWorkflow
from backend.core.comfyui_starter_models import (
    FAMILIES,
    LoaderRecipe,
    loaders,
    node,
    recipe_label,
    resolved_recipe,
)


def starter_workflow(
    family: str, reference: bool = False, *, recipe: LoaderRecipe | None = None
) -> ComfyWorkflow:
    if family not in FAMILIES:
        raise ValueError("Unknown starter workflow family.")
    spec = FAMILIES[family]
    graph, clip, vae = loaders(family, recipe)
    graph.update(
        {
            "positive": node("CLIPTextEncode", clip=clip, text="A traveler with a brass lantern."),
            "negative": node("CLIPTextEncode", clip=clip, text="text, watermark, blurry"),
            "latent": node("EmptyLatentImage", width=1024, height=1024, batch_size=1),
            "sampler": node(
                "KSampler",
                model=["model", 0],
                positive=["positive", 0],
                negative=["negative", 0],
                latent_image=["latent", 0],
                seed=42,
                steps=spec["steps"],
                cfg=spec["cfg"],
                sampler_name=spec["sampler"],
                scheduler=spec["scheduler"],
                denoise=1.0,
            ),
            "decode": node("VAEDecode", samples=["sampler", 0], vae=vae),
            "save": node("SaveImage", images=["decode", 0], filename_prefix="TaleWeaver"),
        }
    )
    bindings = {
        "prompt": ("positive", "text"),
        "negative_prompt": ("negative", "text"),
        "seed": ("sampler", "seed"),
        "width": ("latent", "width"),
        "height": ("latent", "height"),
    }
    if family == "flux1":
        _flux_conditioning(graph, clip, bindings)
    if family in ("sd35", "qwen_image"):
        graph["latent"]["class_type"] = "EmptySD3LatentImage"
    if family == "qwen_image":
        graph["sampling"] = node("ModelSamplingAuraFlow", model=["model", 0], shift=3.1)
        graph["sampler"]["inputs"]["model"] = ["sampling", 0]
    if reference:
        _reference_input(graph, bindings, vae)
    return ComfyWorkflow.model_validate(
        {
            "name": f"General image · {spec['name']} · {'With reference (img2img)' if reference else 'No reference'} · {recipe_label(resolved_recipe(family, recipe))}",
            "graph": graph,
            "bindings": {
                k: {"node_id": pair[0], "input_name": pair[1]} for k, pair in bindings.items()
            },
            "output_node": "save",
            "dimension_multiple": 16
            if family in ("flux1", "anima", "nova_anime_am", "qwen_image", "sd35")
            else 8,
        }
    )


def _flux_conditioning(graph: dict, clip: list, bindings: dict) -> None:
    graph["text"] = node(
        "PrimitiveStringMultiline",
        value="A traveler carries a brass lantern across a stone bridge at dawn.",
    )
    graph["positive"] = node(
        "CLIPTextEncodeFlux", clip=clip, clip_l=["text", 0], t5xxl=["text", 0], guidance=3.5
    )
    graph["negative"] = node("ConditioningZeroOut", conditioning=["positive", 0])
    graph["latent"]["class_type"] = "EmptySD3LatentImage"
    graph["sampler"]["inputs"]["scheduler"] = "simple"
    bindings["prompt"] = ("text", "value")
    del bindings["negative_prompt"]


def _reference_input(graph: dict, bindings: dict, vae: list) -> None:
    del graph["latent"]
    graph["input"] = node("LoadImage", image="reference.png")
    graph["resize"] = node(
        "ImageScale",
        image=["input", 0],
        upscale_method="lanczos",
        width=1024,
        height=1024,
        crop="disabled",
    )
    graph["encode"] = node("VAEEncode", pixels=["resize", 0], vae=vae)
    graph["sampler"]["inputs"].update(latent_image=["encode", 0], denoise=0.3)
    bindings.update(
        image=("input", "image"), width=("resize", "width"), height=("resize", "height")
    )


def starter_catalog() -> list[dict]:
    return [
        {
            "id": key,
            "name": value["name"],
            "generate": starter_workflow(key).model_dump(),
            "reference": starter_workflow(key, True).model_dump(),
        }
        for key, value in FAMILIES.items()
    ]


MODEL_FIELDS = {
    "ckpt_name",
    "unet_name",
    "clip_name",
    "clip_name1",
    "clip_name2",
    "clip_name3",
    "clip_name4",
    "model_name",
    "vae_name",
    "lora_name",
}
CHOICE_FIELDS = MODEL_FIELDS | {"sampler_name", "scheduler"}


def model_choices(workflow: ComfyWorkflow, registry: dict) -> list[dict]:
    result = []
    for key, entry in workflow.graph.items():
        info = registry.get(entry["class_type"], {})
        if not isinstance(info, dict) or not isinstance(info.get("input", {}), dict):
            raise ValueError("Invalid node registry.")
        schema = info.get("input", {})
        if any(not isinstance(schema.get(kind, {}), dict) for kind in ("required", "optional")):
            raise ValueError("Invalid node input schema.")
        fields = {**schema.get("required", {}), **schema.get("optional", {})}
        result.extend(_node_choices(key, entry, fields))
    return result


def _node_choices(key: str, entry: dict, schema: dict) -> list[dict]:
    result = []
    for field, value in entry["inputs"].items():
        if field not in CHOICE_FIELDS or not isinstance(value, str):
            continue
        definition = schema.get(field, [])
        choices = (
            definition[0]
            if isinstance(definition, (list, tuple))
            and definition
            and isinstance(definition[0], list)
            else []
        )
        result.append(
            {
                "node_id": key,
                "input_name": field,
                "choices": [v for v in choices if isinstance(v, str)],
            }
        )
    return result
