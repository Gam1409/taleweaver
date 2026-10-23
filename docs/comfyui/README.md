# ComfyUI image generation (experimental)

Select **ComfyUI (Local)** in either image profile under Admin → Visuals. The
backend must be able to reach the configured URL, for example
`http://127.0.0.1:8188`. Localhost means the backend host/container, not the browser.
Local endpoints require `ALLOW_PRIVATE_NETWORK_MODELS=true`, like other local
providers. SSH tunnels remain external to TaleWeaver.

## Configure a profile

1. Import a **ComfyUI API-format JSON** into the base workflow slot. Editor-format
   JSON with `nodes`/`links` is not supported. Maximum: 256 nodes / 256 KiB per graph.
2. Map the prompt input and final image output node. Optionally map negative prompt,
   seed and dimensions. Choose literal inputs, not connected sockets.
3. Click **Check server compatibility**. This reads `/object_info`; it does not
   generate an image or install nodes/models. Missing node types, known model
   choices, required inputs and mapped inputs are checked. Custom dependencies
   still need a real execution test.
4. Use **Test Generation** for that profile. It uses the unsaved form, including
   the URL and workflow bindings. The selected output must publish an `images`
   result (normally SaveImage). The first image of that output is used.
5. Save Visual Preferences. Workflows are stored in existing settings JSON and
   shared through the existing administrator settings mechanism. No database
   migration is needed. This first version duplicates those settings per user.

Models, encoders, VAE files and custom nodes must already be installed on ComfyUI.
Workflow import does not download dependencies. Model/sampler/steps/CFG/denoise
values remain in the graph. Only mapped inputs are replaced; there is no automatic
translation of provider-specific sampler names or SD/FLUX presets.

The prompt includes the existing TaleWeaver description/style/no-text instructions.
This does not add automatic inventory-to-image composition or translate descriptions.
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

Mapped width/height receive the profile's requested resolution, limited to these
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
ComfyUI and export again if needed. These examples have not been GPU-tested here.

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
- Profiles live in existing settings rather than a separate workflow library.
- Only the current image of the same adventure asset can be selected as input.
  There are no masks, multiple references, video outputs, or automatic custom-node installation.
- PNG preserves transparency, including thumbnails; JPEG intentionally flattens it.
- Images are portable in adventure archives; ComfyUI setup, workflows and model
  dependencies are administrator settings and are not embedded in those archives.
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
- Final ComfyUI suites: 51 passed, including output dimensions/file sizes, oversized
  workflow output, transport timeout and administrator-only draft execution.
- The latest affected regression selection passed 113 existing media/configuration,
  filesystem security and adventure lifecycle tests.
- Full manifest application generated all five visual types through the fake ComfyUI
  transport and verified the Simple/Advanced assignments.
- Chromium verified API JSON import, bindings, compatibility checking, generation
  using unsaved settings, saved settings after reload, and repeated generation.
- Frontend production build passed; TypeScript diagnostics match the previous base
  diagnostic set. New Python modules/tests pass Ruff check and format check.
- Full-file Ruff still reports 36 existing issue locations in legacy image/world-generation
  and asset modules; two legacy files also fail the full-file format check. Unrelated
  broad refactoring was not included.
