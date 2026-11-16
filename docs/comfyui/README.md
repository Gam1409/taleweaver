# ComfyUI image generation

Select **ComfyUI (Local)** under **Administration → Visuals** and enter the API
URL, for example `http://127.0.0.1:8188`. The backend must reach this address:
localhost refers to the backend host/container, not the browser. Local URLs need
`ALLOW_PRIVATE_NETWORK_MODELS=true`; see [provider network policy](../provider-network-policy.md).

## Presets, workflows and assignments

1. Open **Image tasks & presets → Manage presets & assignments**. New libraries
   contain editable Anima and Illustrious task presets. Existing custom libraries
   stay intact; **Add standard presets · Anima + Illustrious** adds missing entries.
2. Create/edit a preset or choose **Create from a task template**. Select the model
   family, image task and actual component layout. The catalogue has 80 recipes:
   ten families and eight tasks. Files and custom nodes must already be installed
   on ComfyUI; TaleWeaver does not download weights or dependencies.
3. Use model/node discovery and choose the exact installed filenames. A unique
   basename can be resolved automatically; unknown or ambiguous files need an
   explicit selection. Static checks cannot inspect checkpoint tensors or VRAM.
4. Configure base and optional reference workflows. Review prompt rules separately
   from graph sampling/loader settings. **Test Generation** tests a draft and does
   not save it or assign it to every task.
5. **Apply to form → Apply assignments → Save Visuals Settings**. Select task
   assignments and the separate test preset. Standard (`simple`) and High-Fidelity
   (`advanced`) profiles also serve other image providers; image-task routing
   determines which configuration actually runs.

See [task recipes](../comfyui-task-templates.md), [preset rules](presets.md) and
[starter architectures](starters.md). A saved adventure/session can retain its own
image settings instead of following later global changes. Check the effective
settings for that target before diagnosing a different model or workflow.

## Import and edit a workflow

The preset editor accepts **ComfyUI API JSON** and supported **editor JSON** with
`nodes`/`links`. Editor graphs are converted to API graphs using server node schemas
and core-node fallbacks; unsupported or ambiguous conversions are reported. The
backend still executes API graphs only. PNG workflow metadata is not a JSON import.

TaleWeaver has a visual graph canvas, an expandable editor, node parameters, raw
JSON and API JSON export. Review automatically suggested bindings after import.
The graph editor handles supported topology and inputs; ComfyUI remains the place
to develop/test custom-node behavior and install its dependencies.

Map the positive prompt, output node and optional negative prompt, image, seed and
dimensions. Bind literal inputs rather than connected sockets. There is one input
image binding; no automatic mask authoring or multi-reference assembly is supplied.
Only mapped inputs change at generation time. Sampling, guidance, LoRA loading and
unmapped inputs remain part of the graph. A1111-style LoRA text alone does not
insert a ComfyUI loader.

Limits are 256 nodes / 256 KiB per graph, 32 presets / 2 MiB for preset data, and
128 saved workflow versions / 4 MiB for the workflow library. A preset pins its
workflow copy; editing another saved workflow does not silently replace every
preset that previously used it.

## References and portraits

A configured reference workflow must have an `image` binding. Eligible editor
regeneration can upload the owned current asset through `/upload/image`. Session
NPC portrait regeneration has its own previous-image option and requested-change
field; see [portrait regeneration](../portrait-regeneration.md).

References require a compatible ComfyUI workflow. Missing/unreadable references or
unsupported providers fail explicitly; the current image is retained on failure.
Ordinary first-image generation does not silently acquire a reference. The built-in
reference variants are img2img at denoise 0.3, not a universal face-identity adapter.
Custom identity/pose adapters must match the model family and installed nodes.

Current main requests **waist-up** NPC/hero portraits, with the entire head visible.
The separate portrait-framing/character-pipeline experiment is paused and is not
part of these defaults. Checkpoint-independent framing, stable identity, automatic
wardrobe/expression fidelity, full sprites and multi-character identity composition
are not established by a successful workflow or a correct state projection.

## Moment illustrations

VN illustrations use the selected completed reply's hash-checked snapshot, rather
than replacing historical clothing/positions with the current session state.
There are two preparation paths, selected by the session content setting:

- **Neutral sessions:** saved visual plans are the default. Frozen public facts
  become one reusable English plan with description/tag surfaces. Deterministic
  description, tags and hybrid compilers produce the selected prompt. The optional
  semantic audit checks the final assembled text; it is not pixel inspection.
- **Content-enabled sessions:** the existing source-based preparation path remains.
  It uses the verified passage and saved facts, existing fidelity checks and a
  bounded feedback retry. Its content/addendum gates remain independent of
  checkpoint-specific formatting; it is not a fallback after a neutral-plan failure.

A cold neutral plan normally uses one normalization call and one audit call when
auditing is enabled; a structural repair can add one call. Exact cached artifacts
need no preparation calls. A compatible format/profile can reuse normalization but
requires its own final-text audit. Saved plans and artifacts share eight records /
2 MiB; rebuild, source/revision changes, copy/import and checkpoint restoration
invalidate derived entries. Canonical state is not changed by image preparation.

**Generation details → Saved visual plan** exposes provenance, limitations and audit
status. **Query** shows bounded preparation exchanges when captured. Declared
coverage and valid IDs do not prove translation accuracy or picture fidelity.
See [shared visual plans](../design/visual-plan-stage2-implementation.md) for the
cache contract and [visual diagnostics](../diagnostics/visual-fidelity.md) for tracing.

## Jobs, cancellation and timeouts

UI jobs use owner-scoped `/api/settings/visual-jobs` requests. Duplicate submissions
and concurrent jobs for the same target are guarded within one backend process.
Job status is in memory and survives for one hour after completion, not a restart.
Run one backend worker; there is no distributed visual-job coordinator.

The adapter polls the exact ComfyUI `prompt_id`, selects the configured image output
and saves the returned image and thumbnails through normal TaleWeaver storage.
**Stop** abandons local processing and tries to remove that queued prompt only.
A running remote task may continue; TaleWeaver does not send a global interrupt.
Check the server before resubmitting an interrupted/unknown remote request.

ComfyUI's configured queue/execution budget defaults to 600 seconds (30–3600).
Individual HTTP operations have separate transport limits. Utility preparation
uses the configured Small-role deadline. Increasing one budget does not change the
others. Failures identify their stage without exposing prompts, credentials or URLs.

## Output bounds

| Asset | Maximum dimensions | Maximum stored size |
| --- | --- | --- |
| Cover | 2048 × 1024 | 4 MiB |
| Scene | 1600 × 900 | 3 MiB |
| Hero / NPC / account avatar | 1024 × 1280 | 2 MiB |
| Item / style preview | 1024 × 1024 | 2 MiB |

Mapped dimensions use the requested profile resolution and workflow alignment.
Unmapped dimensions and downstream upscalers can differ, so output is checked
again. Images are reduced to fit while preserving aspect ratio, without automatic
crop/upscaling; PNG transparency is retained. ComfyUI transport/decode checks reject
responses above 32 MiB or 16 megapixels. These adapter output checks do not assert
identical processing by every other provider.

## Examples and validation

The repository retains [SDXL text](sdxl-text-api.json), [SDXL img2img](sdxl-image-api.json)
and [combined FLUX.1 FP8](flux1-fp8-text-api.json) API examples. Their literal model
filenames must match your server. Task templates are the broader current catalogue;
these example files are not a separate guarantee of installed dependencies.

Offline tests cover graph/binding limits, editor conversion, node discovery,
settings/preset ownership, references, output limits, cancellation, publication and
failure preservation. Historical GPU/browser observations are retained in
[validation history](validation-history.md), [starter coverage](starters.md#historical-live-coverage)
and [the dated setup review](ux-review.md). No new live image-quality result is
claimed by this documentation update. Test your actual checkpoint, encoder, VAE,
custom nodes and task before using a generated image as an identity reference.

## Implementation owners

- [Preset/workflow contracts](../../backend/core/comfyui_config.py) and
  [task recipe catalogue](../../backend/core/comfyui_task_templates.py).
- [Editor JSON conversion](../../frontend/src/services/comfyEditorImport.ts).
- [ComfyUI transport](../../backend/engine/comfyui_client.py) and
  [visual output limits](../../backend/core/visual_limits.py).
- [Moment generation routing](../../backend/engine/scene_illustrations/generation.py)
  and [saved-plan preparation](../../backend/engine/scene_illustrations/plan_preparation.py).
- [Session portrait generation](../../backend/engine/session_portraits.py).
