# ComfyUI task preset templates

The preset library offers **80 recipes: ten model families × eight image tasks**.
`Natural description` is a generic prompt policy, not a checkpoint architecture, so it is not a separate workflow family.

Open **Image tasks & presets → Manage presets & assignments → Create or edit presets → Create from a task template**.
Choose the family, task and model packaging. The result is a new editable preset, not an overwrite of an existing preset. Apply the preset, apply assignments and save Visuals Settings.

The catalogue contains metadata only. Graphs are built on demand; the visual editor still loads only when opened explicitly. No model weights or LoRAs are downloaded or installed.

Workflow names follow **Task · Model family · Reference mode · Component layout**. For example:

- `Story illustration · SD3.5 Large · No reference · AIO`
- `NPC portrait · FLUX.1 Dev · With reference (img2img) · Separate model + encoders + VAE`

Preset names omit the reference mode because they can contain both variants. Generic graph-editor starters are marked `General image`; task presets always name the actual task.

## Architectures and defaults

| Family | Default model loader | Text encoder(s) | VAE | Sampler / scheduler / steps / CFG |
|---|---|---|---|---|
| SD 1.5 | CheckpointLoaderSimple | Embedded CLIP | Embedded | euler / normal / 25 / 7 |
| SDXL | CheckpointLoaderSimple | Embedded CLIP-L + CLIP-G | Embedded | euler / normal / 25 / 7 |
| Pony V6 XL | CheckpointLoaderSimple | Embedded SDXL encoders | Embedded | euler_ancestral / normal / 25 / 7 |
| Illustrious XL | CheckpointLoaderSimple | Embedded SDXL encoders | Embedded | euler_ancestral / normal / 28 / 5 |
| Animagine XL 4.0 | CheckpointLoaderSimple | Embedded SDXL encoders | Embedded | euler_ancestral / normal / 28 / 5 |
| FLUX.1 Dev | Combined FP8 checkpoint | Embedded CLIP-L + T5 | Embedded | euler / simple / 20 / 1; guidance 3.5 |
| SD3.5 Large | CheckpointLoaderSimple | External CLIP-L + CLIP-G + T5 | Embedded | euler / sgm_uniform / 20 / 5 |
| Anima / Prefect Anima | UNETLoader | External Qwen 3 0.6B | External Qwen Image VAE | er_sde / simple / 30 / 4 |
| Nova Anime AM | UNETLoader | External Qwen 3 0.6B | External Qwen Image VAE | er_sde / simple / 30 / 4 |
| Qwen Image | UNETLoader | External Qwen 2.5 VL 7B | External Qwen Image VAE | euler / simple / 20 / 2.5; AuraFlow shift 3.1 |

SD3.5, FLUX and Qwen Image use `EmptySD3LatentImage`. Anima and Nova follow the official Anima blueprint's `EmptyLatentImage` path; the model handles the latent representation.

These are conservative base-model starting points, not measured optimal settings for every derivative. Turbo/distilled, GGUF, edit/inpaint and LoRA-specific variants need a matching custom workflow. Pony inherits the SDXL loader architecture; no Pony-specific custom nodes are required.

## Embedded versus external components

Encoder and VAE sources are independent. A checkpoint may provide both, only one, or neither. External choices insert the appropriate CLIPLoader, DualCLIPLoader or TripleCLIPLoader and/or VAELoader and wire those outputs into conditioning and decoding.

For FLUX, both the documented combined FP8 checkpoint and the full split-file layout are offered. Standard SD3.5 does **not** contain its text encoders: choosing embedded encoders switches the default filename to the documented SD3.5 AIO checkpoint.

Anima, Nova and Qwen default to their documented split-file layout. A custom combined checkpoint requires an explicit filename. ComfyUI supports checkpoint component loading, but neither a filename nor `/object_info` proves that a particular file contains the required tensors. An AIO file must use the architecture and component formats supported by ComfyUI. The supplied Nova file is classified as **Anima** by its model-version metadata; `Checkpoint` in a download catalogue does not establish AIO packaging.

A diffusion-only layout cannot use embedded encoder/VAE selections. File names are starting points, not downloads: replace them with actual server paths. Run **Check models and nodes**, then generate a test image. File/node discovery cannot prove successful GPU execution or image quality.

## Tasks and dimensions

| Task | Existing output bound | Optional reference variant |
|---|---|---|
| NPC portrait | 1024 × 1280 | Yes |
| Hero portrait | 1024 × 1280 | Yes |
| Account avatar | 1024 × 1280 (existing protagonist target) | No by default |
| Inventory item | 1024 × 1024 | Yes |
| Location background | 1600 × 900 | Yes |
| Story illustration | 1600 × 900 | Yes |
| Adventure cover | 2048 × 1024 | Yes |
| Style preview | 1024 × 1024 | No by default |

Template dimensions derive from the shared backend limits and target aspect ratio. The default long edge is 1024 (512 for SD 1.5), rounded down to the architecture's grid. Generation requests may override those defaults using the existing quality-profile settings; ComfyUI input clamping and output byte/dimension limits remain active.

Each preset includes its family prompt policy and task-specific composition guidance. Existing mature-content policy is unchanged and templates do not enable mature content. Optional reference variants use VAEEncode and denoise 0.3: **img2img is not identity conditioning** and is not a Qwen Image Edit workflow. No reference workflow runs without an explicit image supplied by the task.

**Items** also applies a shared composition rule independently of the chosen preset: show the requested object itself on a suitable surface or background. Clothing is unworn and laid flat, without people, living creatures, mannequins or hangers. The rule reaches prompt adaptation, task-aware previews and final generation; supported providers also receive matching negative terms. It adds no LLM requests and leaves portraits, backgrounds and story illustrations unchanged. A checkpoint can still ignore these instructions, so prompt enforcement does not certify the generated image's contents.

## Sources reviewed

Reviewed on 2026-11-04. ComfyUI_examples tree: `f9431bb000ce792094ff345446e22cac1ea6cef3`; ComfyUI core tree: `7f09d3fa4a783868fe39d4d63cf4f815e58abecd`.

- [ComfyUI examples](https://github.com/comfyanonymous/ComfyUI_examples), including embedded API graphs in the official FLUX combined/split, SD3.5 external-encoder/AIO and Qwen Image example PNGs.
- [FLUX](https://github.com/comfyanonymous/ComfyUI_examples/tree/master/flux), [SD3.5](https://github.com/comfyanonymous/ComfyUI_examples/tree/master/sd3), [SDXL](https://github.com/comfyanonymous/ComfyUI_examples/tree/master/sdxl), [Qwen Image](https://github.com/comfyanonymous/ComfyUI_examples/tree/master/qwen_image).
- [Anima model card](https://huggingface.co/circlestone-labs/Anima) and [official Anima blueprint](https://github.com/comfyanonymous/ComfyUI/blob/master/blueprints/Text%20to%20Image%20(Anima).json).
- [Nova Anime AM version metadata](https://civitai.com/api/v1/model-versions/3395337).
- [Animagine XL 4.0](https://huggingface.co/cagliostrolab/animagine-xl-4.0), [Illustrious XL](https://huggingface.co/OnomaAIResearch/Illustrious-xl-early-release-v0), [SD 1.5](https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5).
- ComfyUI `nodes.py`, `comfy_extras/nodes_sd3.py`, `comfy/sd.py` and `comfy/supported_models.py` for loader contracts and embedded component handling.

Validation covers all 80 family/task pairs, component-source combinations, graph links, prompt policies, API permissions, settings persistence, dimensions and mocked generation/upload contracts. It does not substitute for execution with the actual checkpoint files on a ComfyUI GPU server.
