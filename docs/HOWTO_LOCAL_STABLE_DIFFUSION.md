# Local Stable Diffusion with Automatic1111 / Forge

TaleWeaver's **Stable Diffusion (Local)** provider calls the WebUI-compatible
HTTP API. It discovers checkpoints through `/sdapi/v1/sd-models` and generates
through `/sdapi/v1/txt2img`. ComfyUI is a separate provider with its own
[workflow and preset guide](comfyui/README.md).

## Prepare the image server

Install a WebUI version that supports your exact checkpoint architecture, using
its own installation instructions:

- [Automatic1111](https://github.com/AUTOMATIC1111/stable-diffusion-webui)
- [Forge](https://github.com/lllyasviel/stable-diffusion-webui-forge)

TaleWeaver itself requires Python 3.11–3.13; the recommended source setup uses
Python 3.12, Poetry 2.x and Node.js 22. The image server can have a different Python
or CUDA requirement and should use its own environment. See the [project setup](../README.md).

Install checkpoint files, text encoders, VAE and optional extensions according to
that server's documentation. A `.safetensors`, NF4 or GGUF filename does not prove
architecture compatibility or embedded components. A1111 and Forge versions do
not share universal support for every FLUX, quantized or editing model.

Enable the API in the server launcher, for example:

```sh
# webui-user.sh, for a server used on the same machine
export COMMANDLINE_ARGS="--api"
```

```bat
:: webui-user.bat
set COMMANDLINE_ARGS=--api
```

Add `--listen` only when the backend must connect from another host, container,
WSL instance or VM. Configure firewall/access controls for that deployment.
Localhost in TaleWeaver settings means the **backend** machine/container.

Verify the API from that backend environment:

```sh
curl --fail http://127.0.0.1:7860/sdapi/v1/sd-models
```

A response lists the server's discovered checkpoint titles. This is discovery,
not a successful generation or a guarantee that the model fits in VRAM. Install
and test the intended model in the image server before configuring an adventure.

Local/private URLs follow the [provider network policy](provider-network-policy.md).
The direct WebUI adapter has no dedicated Basic-auth fields. Do not put credentials
in a URL; use a separately configured access proxy or another supported provider
when authenticated transport is required.

## Configure TaleWeaver

1. Sign in as an administrator and open **Administration → Visuals**.
2. In **Standard Quality Visuals** and/or **High-Fidelity Visuals (Scenes & Lore)**,
   select **Stable Diffusion (Local)**. Different providers can serve the two profiles.
3. Set **Automatic1111 / Forge API URL**, then **Fetch Checkpoints**. Select the
   actual reported model title, or use an intentional custom identifier. `default`
   leaves the server's currently selected checkpoint in use.
4. Set steps, CFG, sampler, scheduler and minimum long edge in that profile's tuning
   controls. Use settings documented for the exact checkpoint/server combination.
5. Run **Test Generation**, inspect the output, then **Save Visuals Settings**.
6. Review task-to-quality assignments and any saved adventure/session overrides.
   A successful global test does not replace an existing story's saved settings.

The adapter forwards the configured sampler/scheduler names. It does not translate
ComfyUI sampler identifiers, download a model, build a Hires pass or configure a
missing encoder/VAE. WebUI-specific prompt syntax and LoRA handling depend on the
server and installed files/extensions; TaleWeaver forwards the prompt rather than
installing those components. A non-default model title is sent as
`override_settings.sd_model_checkpoint`, so changing profiles may reload weights.

CFG and model-specific guidance are different controls in some architectures.
Do not copy SDXL CFG recommendations directly to FLUX or assume that increasing
CFG repairs every black/noisy output. Quantization, VRAM, resolution, attention
implementation and checkpoint packaging affect both quality and speed; no fixed
hardware/latency guarantee is implied here.

## Verify an adventure

Generate one image before requesting a whole world. Confirm that the selected
model, server URL and task profile match the image you intended. Then create a
small adventure with image generation enabled for the desired asset types, or use
an editor regeneration action. Inspect the image server's errors when a request
fails. First-load and checkpoint-switch time can dominate a small generation job.

NPC/session portrait references and their previous-image workflow currently
require ComfyUI; the direct WebUI adapter here uses `txt2img`. See
[portrait regeneration](portrait-regeneration.md) for that separate capability.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Model discovery fails | API enabled, backend-to-server route, endpoint URL and access controls |
| A checkpoint is absent | Server model folder, architecture support and refreshed model list |
| HTTP 404 | Correct base URL and `/sdapi/v1` API support |
| Out-of-memory failure | Exact model/quantization, resolution, optional extensions and available VRAM |
| Black/noisy or distorted result | Matching checkpoint/encoder/VAE, sampler and checkpoint-author guidance |
| Test works but another image uses different settings | Effective task profile and saved adventure/session overrides |
| Generation times out | `VISUAL_TIMEOUT`, server queue/load time and whether remote work is still running |

Stopping local waiting does not guarantee that an already running remote request
was cancelled. Avoid immediately resubmitting an expensive job without checking
the server. PNG/JPEG settings control stored output; visual correctness still
requires inspecting the actual result.

## Model licenses

Read the license and model card for the exact checkpoint and any additional
weights. Base-model, derivative, adapter and output-use terms can differ; do not
infer output publication rights solely from a family name or TaleWeaver's MIT
code license. Downloading or renaming FLUX Dev weights does not turn them into
Schnell weights. Keep source attribution and applicable notices when redistributing
assets.

## Implementation and related guides

- [WebUI model discovery](../backend/api/routes/config_api.py)
- [Direct image adapter](../backend/engine/media_local_images.py)
- [Profile routing](../backend/engine/image_profiles.py)
- [Image tasks and ComfyUI templates](comfyui-task-templates.md)
- [Debugging](in_game_debugging.md)
