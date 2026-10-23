# ComfyUI image generation (experimental)

Select **ComfyUI (Local)** in either image profile under Admin → Visuals. The
backend must be able to reach the configured URL, for example
`http://127.0.0.1:8188`. Localhost means the backend host/container, not the browser.
Local endpoints require `ALLOW_PRIVATE_NETWORK_MODELS=true`, like other local
providers. SSH tunnels remain external to TaleWeaver.

## Configure a preset and assign it to a profile

1. Enter the ComfyUI API URL, then choose **New preset** in the Standard or
   High-Fidelity card. Select a model family under **Start from a template** and
   click **Use starter workflow**. The app fills bindings, resolves unique matching
   filenames to their server folders, and checks compatibility automatically.
2. Verify the model files once. If a filename is unknown or ambiguous, select the
   installed file. **Generation parameters** holds steps, CFG, guidance, denoise,
   sampler and scheduler; normal generation reuses these saved values.
3. Automatic prompt-template selection supplies the model family's rules. The
   configured Small / Utility LLM adapts each asset description automatically.
   Fine-tuning the rules is optional; see [prompt presets](presets.md).
4. Optionally expand **Use a previous image** and choose a matching starter. The
   suggested family and compatible loader filenames come from the base workflow.
5. **Apply to form**, use **Test Generation**, then **Save Visuals Settings**.
   This is a one-time setup per preset; covers, scenes, portraits, items, account
   avatars and catalog tiles receive their prompt and dimensions automatically.

For a custom graph, import a **ComfyUI API-format JSON** exported with **File →
Export (API)** in ComfyUI (older interfaces require developer mode). Editor-format
JSON with `nodes`/`links` is not supported. Maximum: 256 nodes / 256 KiB per graph.
Map the prompt and final image output under **Advanced: workflow inputs and
output**; incomplete mappings open this section automatically. Optional bindings
include negative prompt, seed and dimensions. Bind literal inputs, not sockets.

**Advanced: edit or export workflow JSON** supports direct graph edits and download.
Invalid JSON leaves the draft unchanged. Removed/connected inputs lose their
bindings and must be remapped. Export includes the API graph; TaleWeaver bindings
and prompt rules remain in the saved preset. Use ComfyUI for visual node editing.

**Check server compatibility** reads `/object_info`; it does not execute or install
anything. It checks node types, known model choices, required inputs and bindings.
A real image test is still needed to verify runtime dependencies and VRAM. The
selected output must publish `images` (normally SaveImage); its first image is used.

See [starter families and validation](starters.md) for dependencies and test coverage.

Models, encoders, VAE files and custom nodes must already be installed on ComfyUI.
Workflow import does not download dependencies. Model/sampler/steps/CFG/denoise
values remain in the graph. Only mapped inputs are replaced; there is no automatic
translation of provider-specific sampler names. Prompt templates change text only.

Existing workflows migrate into named presets with their previous prompt behavior.
Selecting a prompt template enables model-specific formatting and optional language
adaptation. This does not add automatic inventory-to-image composition.
An unmapped seed remains fixed in the workflow. A mapped seed uses the configured
TaleWeaver seed, or a fresh seed when it is absent/negative.

## Image dimensions and file sizes

ComfyUI outputs use the same limits as TaleWeaver's existing adventure uploads:

| Asset | Maximum dimensions | Maximum file size |
|---|---|---|
| Cover | 2048 × 1024 | 4 MiB |
| Scene | 1600 × 900 | 3 MiB |
| Protagonist / NPC | 1024 × 1280 | 2 MiB |
| Item | 1024 × 1024 | 2 MiB |

Mapped width/height receive the profile's requested resolution and workflow-specific
alignment (8/16/32/64 pixels), limited to these
bounds (rounded down to multiples of eight when reduced). Unmapped dimensions
remain in the workflow. An upscaler or other downstream node can still change the
result, so the final downloaded image is checked separately and reduced to fit.
Aspect ratio is preserved, with no crop or upscaling. High-entropy files that still
exceed the byte limit are reduced further. PNG retains transparency. Account
avatars use portrait limits, catalog examples use item limits, and test generation
uses portrait limits. These new output checks apply to ComfyUI; other providers
retain their existing generation behavior.

Transport/decode safeguards reject responses larger than 32 MiB or 16 megapixels
before saving. Workflows intended to produce very large images should resize at
their output node rather than relying on TaleWeaver to decode them.

## Standard SDXL examples

`sdxl-text-api.json` is a standard text-to-image graph. It assumes the checkpoint
is named `sd_xl_base_1.0.safetensors`; adjust it to the actual server filename in
ComfyUI and export again if needed. Both SDXL examples were exercised on an A40
with ComfyUI 0.42.5; this does not guarantee every server/custom-node combination.

| Binding | Text workflow | Image workflow |
|---|---|---|
| prompt | `2.text` | `2.text` |
| negative_prompt | `3.text` | `3.text` |
| seed | `5.seed` | `5.seed` |
| width / height | `4.width` / `4.height` | `8.width` / `8.height` |
| image | None | `4.image` |
| Output node | `7` | `7` |

`sdxl-image-api.json` is ordinary img2img with denoise 0.55. It is not a face-identity
adapter. For identity/style references, import a workflow designed for that task
with its own compatible nodes/models and map its input image.

## FLUX.1 Dev FP8 example

`flux1-fp8-text-api.json` adapts the [official FLUX example](https://docs.comfy.org/tutorials/flux/flux-1-text-to-image)
to the combined `flux1-dev-fp8.safetensors` checkpoint. It includes model, encoders
and VAE in that checkpoint; a diffusion-only file requires a different loader graph.
The graph keeps the example's 20 steps, CFG 1 and guidance 3.5. A shared
`PrimitiveStringMultiline` feeds both `clip_l` and `t5xxl` of `CLIPTextEncodeFlux`.

| Binding | Input |
|---|---|
| prompt | `100.value` |
| seed | `31.seed` |
| width / height | `27.width` / `27.height` |
| Output node | `9` |

There is no negative-text binding: this workflow uses `ConditioningZeroOut`.
The equivalent graph was tested with the installed checkpoint's folder prefix
on the live A40 server. Older ComfyUI versions may need an update for the string node.

## Use the current image

Add a second API graph to the optional **Image workflow** slot and map `image`.
In the adventure editor's Manual Vision Weaver, select the profile and enable
**Use current image with ComfyUI image workflow**. The backend checks ownership,
reads the existing full-size image, uploads it via `/upload/image`, then uses the
returned filename in the mapped input. Remote URLs and files outside the current
adventure's library are rejected. Missing files and SVG placeholders are not references.

The old image stays active if generation fails. Quick regeneration and world creation
use the base graph; they do not silently reuse a reference. There is no automatic
visual update each turn, pinned identity reference or gallery of previous versions.

## Profiles and jobs

Simple/Advanced is respected across generation and regeneration; an explicit manual
selection overrides the content-type default. Covers default to Advanced. Account
avatars and catalog examples use Simple. Mixed providers remain supported.

UI generation uses owner-scoped jobs at `/api/settings/visual-jobs` and short status
requests. A duplicate job ID does not submit another task during that backend
process's lifetime. Concurrent UI jobs for the same user/target are rejected.
The ComfyUI adapter polls the exact `prompt_id`, reads only the configured output
and downloads the result into TaleWeaver's normal storage, including thumbnails.
Existing adventure export/import therefore continues to package final images.

The queue/execution timeout is configurable from 30 to 3600 seconds. Transport
requests have separate timeouts. Submission is never blindly retried. An interrupted
submission can leave an unknown remote job; check ComfyUI before resubmitting.

**Stop** abandons local processing and tries to delete only that queued ComfyUI
prompt. An already running remote task may continue. TaleWeaver never sends a global
interrupt or clears another client's queue. Cancelling legacy threaded providers
may also leave their remote work running.

## First-version limits

- Jobs are held in memory for one backend process and retained for one hour after
  completion. A backend restart loses job status; there is no durable worker queue
  or multi-worker coordination. Do not automatically resubmit a lost job.
- The named preset library lives in existing administrator settings JSON. Story
  editors can override the Standard and High-Fidelity assignments under Visuals →
  Image generation presets. New stories inherit shared settings.
- Only the current image of the same adventure asset can be selected as input.
  There are no masks, multiple references, video outputs, or automatic custom-node installation.
- PNG preserves transparency, including thumbnails; JPEG intentionally flattens it.
- Images and selected preset IDs are portable in adventure archives; ComfyUI setup,
  workflows and model dependencies are administrator settings and are not embedded
  in those archives. Re-select missing preset IDs after importing on another server.
- Compatibility checks are static and cannot guarantee available VRAM or working
  Python/native dependencies inside custom nodes.

## Validation

Automated tests use a fake ComfyUI HTTP transport and isolated SQLite databases.
They cover workflow typing/bindings, node checks, image saving, reference upload,
profile selection, settings round-trips, job ownership, duplicate submissions,
failure preservation and cancellation without global interruption. Live workflows
must still be tested against the actual user's ComfyUI installation.

Branch validation results:

- Broad selection: 226 passed, three pre-existing failures in `test_adventures_api.py`
  (legacy consumable import, readable inventory snapshot, and manifest start scene).
- Earlier preset update: 118 tests passed across ComfyUI, prompt presets, existing media
  behavior and adventure lifecycle suites. This includes timeout before image
  submission, automatic/manual rules, profile overrides, settings persistence and
  preset IDs surviving cloning/export/import.
- The latest affected regression selection passed 113 existing media/configuration,
  filesystem security and adventure lifecycle tests.
- Full manifest application generated all five visual types through the fake ComfyUI
  transport and verified the Simple/Advanced assignments.
- Chromium verified API JSON import, bindings, compatibility checking, generation
  using unsaved settings, saved settings after reload, and repeated generation.
- Live ComfyUI 0.42.5 on NVIDIA A40 generated a five-image world with SDXL/FLUX
  assignments and then processed the previous scene via img2img. The six initial
  remote jobs completed in approximately 16–29 seconds each. Required nodes/models
  and filename detection were checked against the real server. LLM adaptation was
  disabled for these GPU tests; its routing and assembly were tested with mocks.
- Two further GPU jobs passed: generation through the browser's background-job flow
  and a reference comparison at denoise 0.25 (about 13 seconds end to end). The latter
  retained the original lighthouse/boat/pier much better than denoise 0.55, which
  changed major structures. Eight live jobs succeeded in that earlier round. This is transport
  and workflow validation, not a guarantee of exact semantic/identity preservation.
- Chromium saved a story-specific preset, verified it after reload and restored its
  original choice; desktop and mobile drawer layouts were inspected.
- Frontend production build passed; TypeScript diagnostics match the previous base
  diagnostic set. New Python modules/tests pass Ruff check and format check.
- Full-file Ruff reports 39 existing diagnostics in modified legacy files, compared
  with 40 on the same files at the previous commit; no new diagnostic locations.
  Two legacy files still fail the full-file format check. New modules pass both.

The final starter-workflow regression selection passed **166 tests**. All nine
Python modules/tests changed in this update pass Ruff check and format check. The
frontend production build passes with no additional TypeScript diagnostics relative
to the preceding commit.

The starter-workflow update adds 24 successful live jobs (eight each for SDXL,
FLUX.1 Dev FP8 and Prefect Anima), plus an initial Anima smoke image. The family
matrix and current limitations are documented in [starters.md](starters.md).

The current setup flow and accessibility limits are recorded in the [UI review](ux-review.md).
