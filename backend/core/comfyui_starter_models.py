"""Loader recipes from upstream ComfyUI examples; filenames never prove AIO contents."""

from typing import Any, Literal

from pydantic import BaseModel, Field

Layout = Literal["checkpoint", "diffusion"]
ComponentSource = Literal["embedded", "external"]
EXAMPLES = "https://github.com/comfyanonymous/ComfyUI_examples/tree/master/"
ANIMA_SOURCE = "https://huggingface.co/circlestone-labs/Anima"

FAMILIES: dict[str, dict[str, Any]] = {
    "sd15": dict(
        name="Stable Diffusion 1.5",
        architecture="sd15",
        checkpoint="v1-5-pruned-emaonly.safetensors",
        cfg=7.0,
        steps=25,
        sampler="euler",
        scheduler="normal",
        sources=[EXAMPLES, "https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5"],
    ),
    "sdxl": dict(
        name="SDXL",
        architecture="sdxl",
        checkpoint="sd_xl_base_1.0.safetensors",
        cfg=7.0,
        steps=25,
        sampler="euler",
        scheduler="normal",
        sources=[EXAMPLES + "sdxl"],
    ),
    "pony6": dict(
        name="Pony Diffusion V6 XL",
        architecture="sdxl",
        checkpoint="ponyDiffusionV6XL_v6StartWithThisOne.safetensors",
        cfg=7.0,
        steps=25,
        sampler="euler_ancestral",
        scheduler="normal",
        sources=[EXAMPLES + "sdxl", "https://civitai.com/models/257749/pony-diffusion-v6-xl"],
    ),
    "illustrious": dict(
        name="Illustrious XL",
        architecture="sdxl",
        checkpoint="illustriousXL_v01.safetensors",
        cfg=5.0,
        steps=28,
        sampler="euler_ancestral",
        scheduler="normal",
        sources=[
            EXAMPLES + "sdxl",
            "https://huggingface.co/OnomaAIResearch/Illustrious-xl-early-release-v0",
        ],
    ),
    "animagine4": dict(
        name="Animagine XL 4.0",
        architecture="sdxl",
        checkpoint="animagine-xl-4.0-opt.safetensors",
        cfg=5.0,
        steps=28,
        sampler="euler_ancestral",
        scheduler="normal",
        sources=[EXAMPLES + "sdxl", "https://huggingface.co/cagliostrolab/animagine-xl-4.0"],
    ),
    "flux1": dict(
        name="FLUX.1 Dev",
        architecture="flux",
        checkpoint="flux1-dev-fp8.safetensors",
        diffusion="flux1-dev.safetensors",
        cfg=1.0,
        steps=20,
        sampler="euler",
        scheduler="simple",
        sources=[EXAMPLES + "flux"],
    ),
    "sd35": dict(
        name="SD3.5 Large",
        architecture="sd3",
        checkpoint="sd3.5_large.safetensors",
        aio_checkpoint="sd3.5_large_fp8_scaled.safetensors",
        cfg=5.0,
        steps=20,
        sampler="euler",
        scheduler="sgm_uniform",
        sources=[EXAMPLES + "sd3"],
    ),
    "anima": dict(
        name="Anima / Prefect Anima",
        architecture="anima",
        diffusion="anima-base-v1.0.safetensors",
        cfg=4.0,
        steps=30,
        sampler="er_sde",
        scheduler="simple",
        sources=[
            ANIMA_SOURCE,
            "https://github.com/comfyanonymous/ComfyUI/blob/master/blueprints/Text%20to%20Image%20(Anima).json",
        ],
    ),
    "nova_anime_am": dict(
        name="Nova Anime AM",
        architecture="anima",
        diffusion="novaAnimeAM_v6029B.safetensors",
        cfg=4.0,
        steps=30,
        sampler="er_sde",
        scheduler="simple",
        sources=[ANIMA_SOURCE, "https://civitai.com/api/v1/model-versions/3395337"],
    ),
    "qwen_image": dict(
        name="Qwen Image",
        architecture="qwen_image",
        diffusion="qwen_image_fp8_e4m3fn.safetensors",
        cfg=2.5,
        steps=20,
        sampler="euler",
        scheduler="simple",
        sources=[EXAMPLES + "qwen_image"],
    ),
}


class LoaderRecipe(BaseModel):
    layout: Layout | None = None
    encoder_source: ComponentSource | None = None
    vae_source: ComponentSource | None = None
    checkpoint_name: str | None = Field(default=None, min_length=1, max_length=240)


def node(kind: str, **inputs: Any) -> dict:
    return {"class_type": kind, "inputs": inputs}


def default_recipe(family: str) -> dict:
    spec = FAMILIES[family]
    split = "checkpoint" not in spec
    return {
        "layout": "diffusion" if split else "checkpoint",
        "encoder_source": "external" if split or family == "sd35" else "embedded",
        "vae_source": "external" if split else "embedded",
    }


def resolved_recipe(family: str, recipe: LoaderRecipe | None = None) -> dict:
    spec = FAMILIES[family]
    chosen = recipe or LoaderRecipe()
    defaults = default_recipe(family)
    layout = chosen.layout or defaults["layout"]
    external = layout == "diffusion"
    encoder = chosen.encoder_source or ("external" if external else defaults["encoder_source"])
    vae = chosen.vae_source or ("external" if external else defaults["vae_source"])
    if external and (encoder == "embedded" or vae == "embedded"):
        raise ValueError("A diffusion-only file needs external text encoders and VAE.")
    if external and "diffusion" not in spec:
        raise ValueError(
            "This family template uses a checkpoint. Import a custom split workflow instead."
        )
    filename = chosen.checkpoint_name or spec.get("diffusion" if external else "checkpoint")
    if not external and encoder == "embedded" and "aio_checkpoint" in spec:
        filename = chosen.checkpoint_name or spec["aio_checkpoint"]
    if not filename:
        raise ValueError(
            "Enter the filename of your custom combined checkpoint; its contents must match the selected components."
        )
    return dict(layout=layout, encoder_source=encoder, vae_source=vae, filename=filename)


def recipe_label(chosen: dict) -> str:
    """Describe the selected component wiring, not inferred file contents."""
    if chosen["layout"] == "diffusion":
        return "Separate model + encoders + VAE"
    external = [
        label
        for key, label in (("encoder_source", "encoders"), ("vae_source", "VAE"))
        if chosen[key] == "external"
    ]
    return "External " + " + ".join(external) if external else "AIO"


def loaders(family: str, recipe: LoaderRecipe | None = None) -> tuple[dict, list, list]:
    spec = FAMILIES[family]
    chosen = resolved_recipe(family, recipe)
    graph = {"model": node("CheckpointLoaderSimple", ckpt_name=chosen["filename"])}
    if chosen["layout"] == "diffusion":
        graph["model"] = node("UNETLoader", unet_name=chosen["filename"], weight_dtype="default")
    clip, vae = ["model", 1], ["model", 2]
    if chosen["encoder_source"] == "external":
        graph["clip"] = encoder_loader(spec["architecture"])
        clip = ["clip", 0]
    if chosen["vae_source"] == "external":
        filename = {
            "sd15": "vae-ft-mse-840000-ema-pruned.safetensors",
            "sdxl": "sdxl_vae.safetensors",
            "sd3": "sd3_vae.safetensors",
            "flux": "ae.safetensors",
            "anima": "qwen_image_vae.safetensors",
            "qwen_image": "qwen_image_vae.safetensors",
        }[spec["architecture"]]
        graph["vae"] = node("VAELoader", vae_name=filename)
        vae = ["vae", 0]
    return graph, clip, vae


def encoder_loader(architecture: str) -> dict:
    if architecture == "sd3":
        return node(
            "TripleCLIPLoader",
            clip_name1="clip_l.safetensors",
            clip_name2="clip_g.safetensors",
            clip_name3="t5xxl_fp16.safetensors",
        )
    if architecture in ("sdxl", "flux"):
        return node(
            "DualCLIPLoader",
            clip_name1="clip_l.safetensors",
            clip_name2="clip_g.safetensors" if architecture == "sdxl" else "t5xxl_fp16.safetensors",
            type=architecture,
            device="default",
        )
    filename, kind = {
        "sd15": ("clip_l.safetensors", "stable_diffusion"),
        "anima": ("qwen_3_06b_base.safetensors", "stable_diffusion"),
        "qwen_image": ("qwen_2.5_vl_7b_fp8_scaled.safetensors", "qwen_image"),
    }[architecture]
    return node("CLIPLoader", clip_name=filename, type=kind, device="default")
