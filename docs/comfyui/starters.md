# Starter workflows and validation

The preset editor generates two API graphs for each supported starter family:
text-to-image and optional img2img. There is one implementation in
`backend/core/comfyui_starters.py`; the UI can export any graph as JSON. Each graph
serves covers, backgrounds/scenes, protagonist and NPC portraits, objects, account
avatars and catalog tiles. Separate files for every aspect ratio are unnecessary.
TaleWeaver fills the mapped dimensions from the asset type and quality profile.

| Starter | Loaders / files | Default sampling | Alignment |
|---|---|---|---|
| SDXL | Combined checkpoint | 25 steps, CFG 7, Euler / normal | 8 px |
| Illustrious XL | SDXL architecture, Illustrious checkpoint | 28 steps, CFG 5, Euler ancestral / normal | 8 px |
| Animagine XL 4.0 | SDXL architecture, Animagine 4.0 checkpoint | 28 steps, CFG 7, Euler ancestral / normal | 8 px |
| FLUX.1 Dev FP8 | Combined checkpoint containing model, encoders and VAE | 20 steps, CFG 1, guidance 3.5, Euler / simple | 16 px |
| Anima / Prefect Anima | Diffusion model + Qwen-3 0.6B encoder + Qwen Image VAE | 30 steps, CFG 4, er_sde / simple | 16 px |

These are starting points for the named architectures. Split FLUX loaders, Turbo,
Edit/Kontext, masks and identity adapters need an appropriate custom graph. LoRA
weights stay in the graph; a prompt template does not alter sampling settings.

Anima is based on Cosmos-Predict2 and is **not** Animagine or an SDXL derivative.
Its starter follows the official Anima graph: `UNETLoader`, `CLIPLoader` with
`type=stable_diffusion`, `VAELoader`, `EmptyLatentImage` and normal CLIP conditioning.
Default files are `prefectAnima_v10.safetensors`, `qwen_3_06b_base.safetensors` and
`qwen_image_vae.safetensors`. The public Prefect Anima v1.0 metadata identifies its
base family as Anima; its derivative card did not provide separate sampler advice.

References:

- [Official ComfyUI Anima tutorial](https://docs.comfy.org/tutorials/image/anima/anima)
- [Anima author card](https://huggingface.co/circlestone-labs/Anima)
- [Official FLUX.1 tutorial](https://docs.comfy.org/tutorials/flux/flux-1-text-to-image)
- [Illustrious author card](https://huggingface.co/OnomaAIResearch/Illustrious-xl-early-release-v0)
- [Animagine XL 4.0 author card](https://huggingface.co/cagliostrolab/animagine-xl-4.0)

## One-time setup and normal use

Choose a family once. The app queries installed filenames and resolves a matching
basename only when it is unique; it never silently substitutes another checkpoint.
An unknown or ambiguous model needs one explicit selection. The compatibility
report identifies missing nodes/files before an image test. Model installation and
custom-node dependency management remain outside TaleWeaver.

The optional image starter inherits matching loader filenames from the base graph.
Its default denoise is 0.3; a resized source image is encoded through the model's VAE.
This preserves composition approximately and does not guarantee facial identity or
exact objects. Changing lighting substantially may require a purpose-built editing
workflow. Repeatedly tuning settings is not part of normal gameplay.

Model files stay visible. Sampling controls, raw JSON and input bindings are in
accordions; incomplete bindings open automatically. Advanced JSON edits preserve
valid mappings and discard mappings to removed/connected inputs. Workflow changes
are draft changes until **Apply to form** and **Save Visuals Settings**.

## Live coverage

On ComfyUI 0.42.5 with an NVIDIA A40 (48 GB), all 24 jobs in this matrix completed:

| Family | Cover | Hero | Scene | NPC | Item | Account avatar | Catalog tile | Scene img2img |
|---|---|---|---|---|---|---|---|---|
| SDXL Base 1.0 | Pass | Pass | Pass | Pass | Pass | Pass | Pass | Pass |
| FLUX.1 Dev FP8 | Pass | Pass | Pass | Pass | Pass | Pass | Pass | Pass |
| Prefect Anima v1.0 | Pass | Pass | Pass | Pass | Pass | Pass | Pass | Pass |
| Illustrious XL | Not installed | — | — | — | — | — | — | — |
| Animagine XL 4.0 | Not installed | — | — | — | — | — | — | — |

Five world images per family went through full manifest application, with stored
preset IDs verified afterward. Account/avatar and catalog tests used their real
route handlers. Reference regeneration uploaded the prior scene. Requested and
returned sizes, selected checkpoint, duration and successful storage were recorded.
The requested long edge was 1024 px; shapes were 1024×512 covers, 1024×576 scenes,
816×1024 portraits and 1024×1024 objects. Matrix jobs took approximately 8–21 seconds
each. An initial smaller Anima smoke image also succeeded, taking 75 seconds.

The live tests disabled LLM prompt adaptation to isolate the image workflows.
LLM routing, required prompt tokens, timeout behavior and non-graphic mature-theme
instructions are covered with mocked LLM responses. A full live LLM-to-image quality
benchmark remains outside this validation. Anima's reference result kept the main
harbor composition; one unadapted item image included unwanted lettering. Review
found that disabled adaptation forwarded structured asset metadata; it now forwards
only the visual description, verified by a regression test. That final correction
was not retested on the GPU after the server was released.

All ten starter graphs were checked against a locally saved copy of the live node
registry. The only compatibility errors for Illustrious/Animagine were their missing
checkpoint filenames. Automated tests exercise prompt/seed/dimension binding and
reference upload for all five families; this does not replace live model execution.
