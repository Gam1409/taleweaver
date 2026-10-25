# Generation presets and prompt templates

A generation preset combines an API workflow, optional reference workflow and text
rules. It does not change your model weights. The Standard and High-Fidelity cards
select presets; **Configure** opens a drawer with Workflow and Prompt tabs.
Additional text controls and prompt preview stay collapsed until needed.

## Choosing a model template

New presets enable **Choose template automatically from the workflow model**.
TaleWeaver reads literal checkpoint/diffusion-model filenames from supported loader
nodes. It ignores LoRA, VAE and text-encoder filenames. This is a filename hint,
not architecture detection or inspection of model weights.

Automatic selection requires every discovered base-model name to match the same
known family. If a reference graph exists, it must match that family too. Unknown,
renamed, mixed, editing or refiner models require a manual choice. A failed match
does not silently reuse stale rules. Custom loaders or connected model-name inputs
may need manual selection even when their workflows execute correctly.

Selecting a template or editing any rule disables automatic selection. Manual rules
survive workflow changes and settings reloads. Turning automatic selection back on
replaces them with the detected template. The backend repeats detection when it
validates settings and prepares generation, rather than trusting stale UI results.

| Template | Starting point |
|---|---|
| Natural description | Neutral subject, action, setting, lighting, composition |
| Stable Diffusion 1.5 | Concise description and concrete style tags |
| SDXL | Description with lighting/composition tags |
| FLUX.1 | Connected sentences, without quality-score tags |
| Stable Diffusion 3.5 | Precise connected description |
| Pony Diffusion V6 XL | Visual tags with V6 score prefix |
| Illustrious XL | Visual tags, without forced Pony scores |
| Animagine XL 4.0 | Ordered tags and the author's 4.0 quality suffix |
| Anima / Prefect Anima | Illustration tags and descriptive sentences; separate from Animagine XL |
| Qwen-Image | Detailed description with counts and spatial relationships |

These are editable starting points. A derivative can have different requirements.
Version-specific rules are not applied to every similarly named release. The
template selector links its source and notes known limitations. The SD3.5 and Pony
author cards were inaccessible during review; their notes explicitly distinguish
conservative/community conventions from verified author guidance.

## How text reaches ComfyUI

1. Resolve the story's Standard/High-Fidelity selection and any explicit manual
   quality override. Other image providers keep their existing behavior.
2. Build visual source facts from the asset description, selected art style and
   available mood. This does not extract a complete inventory or infer hidden facts
   from the game state.
3. When enabled, ask the configured **Small / Utility LLM** to adapt those facts to
   the template's format, language, instructions and word budget. This adds an LLM
   call per generated asset, with a 90-second timeout. An error aborts that image
   request before submitting a ComfyUI job; no hidden format fallback is used.
4. Assemble required prefix, body and suffix in code. The LLM does not produce
   workflow JSON, CFG, steps, LoRA strengths or required trigger tokens.
5. Replace only the mapped workflow inputs. Existing negative text is combined with
   global and template negatives only if a negative input is mapped. Sampler,
   guidance, denoise and unmapped conditioning stay in the graph.

**Suggest Prompt** returns the editable body using the selected profile's rules.
Manually supplied text skips automatic adaptation at generation time; prefix and
suffix are still appended once. Enter only the body in that field. Preview shows
the assembled text but is not a test of the model's text encoder or image quality.
Disabling LLM adaptation also disables automatic translation and formatting; the
visible description is used directly with the required prefix/suffix. Structured
asset metadata and plot context are not forwarded as raw JSON when adaptation is off.

A word budget is not a tokenizer/context-window guarantee, especially for languages
without spaces. Use the actual encoder's limits. Template language defaults to
English independently of the story's content language, and can be changed manually.

## Workflow details that matter

- Export **API format** from ComfyUI after verifying the workflow there. Ordinary
  editor JSON and template image/PNG metadata are not direct `/prompt` payloads.
- Models, matching encoders/VAE files, custom nodes and their Python dependencies
  must already be installed. `/object_info` verifies registered node types and known
  input/model choices. It cannot prove GPU memory availability or runtime dependency
  compatibility. Run **Test Generation** against the actual installation.
- Standard ComfyUI CLIP encoding supports weighting such as `(red coat:1.2)`, but
  that is not a universal rule for every encoder/custom node. Prefix/suffix can hold
  deliberate syntax; templates do not invent weights automatically.
- ComfyUI's frontend expands dynamic choices such as `{day|night}` before queuing.
  TaleWeaver's direct API integration does not perform that frontend expansion.
- LoRA loading and strength belong in the graph's loader nodes. A1111-style
  `<lora:name:weight>` text does not automatically load a LoRA through this adapter.
  Add required trigger words explicitly to prefix/suffix. Embedding syntax similarly
  requires an installed embedding compatible with the encoder.
- There is one positive and one optional negative text binding per workflow. For
  multiple encoder inputs, expose one literal string input in your API graph and
  connect it to the relevant nodes, or keep deliberately fixed secondary prompts.
  TaleWeaver does not guess how to update every encoder/refiner prompt.
- Prompt rules apply to both graphs in one preset. Use separate presets when an
  editing model needs different change/preservation instructions. Uploading an image
  alone does not guarantee identity preservation; that depends on the workflow.
- Image dimensions and storage limits still follow [the provider guide](README.md).
  Choose a model-appropriate generation resolution and explicitly resize the output
  in ComfyUI when needed. Prompt templates do not rewrite dimension or sampling nodes.

This provider targets the self-hosted ComfyUI API. Comfy Cloud authentication and
partner API node credentials are not configured by it.

## Story selection and compatibility

Save Visual Preferences after applying a preset to the form. Changes to a shared
preset affect every profile/story referring to it. **Save as new** makes a separate
copy before applying it to the form. The library is limited to 32 presets / 2 MiB;
each graph remains limited to 256 nodes / 256 KiB.

In an existing adventure, open **Visuals → Image generation presets** and select
Standard and/or High-Fidelity overrides. New stories inherit shared settings until
changed in the editor. Existing images are not regenerated by saving this selection.
Copy/export/import retains preset IDs, but does not embed server URLs, workflow
graphs or model dependencies. A missing ID produces an explicit error and must be
reselected; generation does not silently fall back to another model.

Older two-slot ComfyUI settings migrate to named presets with no prompt adaptation
enabled. This preserves their graphs, bindings and previous text construction.

## Sources reviewed

Official sources:

- [ComfyUI repository and prompt syntax](https://github.com/Comfy-Org/ComfyUI)
- [Official basic API example](https://github.com/Comfy-Org/ComfyUI/blob/master/script_examples/basic_api_example.py)
- [Server routes](https://docs.comfy.org/development/comfyui-server/comms_routes)
- [Dependencies](https://docs.comfy.org/basic-concepts/dependencies)
- [Workflow templates](https://docs.comfy.org/interface/features/template)
- [FLUX.1 workflow](https://docs.comfy.org/tutorials/flux/flux-1-text-to-image)
- [Qwen-Image workflow](https://docs.comfy.org/tutorials/image/qwen/qwen-image)
- [Comfy website](https://comfyui.com/) and [documentation index](https://docs.comfy.org/)

Author model cards for SD1.5, SDXL, Illustrious, Animagine 4.0 and Qwen-Image are
linked from the template catalog. The [ComfyUI Wiki workflow collection](https://comfyui-wiki.com/en/workflows),
including [SDXL](https://comfyui-wiki.com/en/workflows/sdxl),
[img2img](https://comfyui-wiki.com/en/workflows/img2img) and
[LoRA](https://comfyui-wiki.com/en/workflows/lora), was also reviewed as a **community,
non-official** source. These references describe workflow behavior; they do not
establish one universal prompting convention for all checkpoints.

## Non-graphic mature themes

The pink **Взрослая тематика** checkbox in a preset's Prompt tab is off by default.
With Small / Utility LLM adaptation enabled, it permits romantic tension, flirting
and implied intimacy between clearly adult characters when consistent with the
scene. It does not introduce sexual context, explicit acts, intimate anatomy or
graphic details, and excludes minors and age-ambiguous characters. The preference
is stored separately from automatic template selection, so detecting another model
does not reset it. It affects LLM prompt adaptation only; manual prompts and workflow
JSON/sampling controls remain unchanged.
# Checkpoint VAE versus a separate VAE

The SDXL, Illustrious, Animagine and combined FLUX checkpoint starters connect
`CheckpointLoaderSimple` output 2 directly to `VAEDecode`. Their reference workflows
also connect that same output to `VAEEncode`. They do not require a separate VAE file
in `models/vae`, and an empty server VAE list does not make these workflows incompatible.
The settings display this checkpoint connection explicitly.

Anima's split-model starter uses `VAELoader` and requires its selected external VAE.
Imported workflows follow their actual node connections: a `VAELoader` node still
requires its file even if some other checkpoint also contains a VAE. Removing or
replacing that node requires rewiring its consumers in the workflow JSON.

The compatibility check verifies node availability and selected filenames, not the
weights inside a checkpoint. A checkpoint without a usable embedded VAE can pass
static checks and fail when ComfyUI executes it. Use a test image to confirm actual
loading and decoding. The checkpoint's filename alone is not reliable evidence.
