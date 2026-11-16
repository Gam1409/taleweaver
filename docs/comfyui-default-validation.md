# Default ComfyUI workflow validation

Status: **live validation performed on 2026-11-06**, using ComfyUI 0.35.0 on an NVIDIA A40. Four installed checkpoints covered three registered families: Nova Anime AM, Illustrious (WAI v17), and SD 1.5 (Counterfeit V3 and Majicmix v7). The 77-case baseline completed without submission or execution failures. Other registered families still need their own live runs.

**Artistic readiness is not established by successful execution.** The baseline exposed inconsistent portrait crops, garment duplicates, unwanted wearers/mannequins and material changes. Additional sampler, embedding, upscale and presentation experiments are separate from the baseline; no experimental sampler combination was promoted to a universal default.

## Standard preset library

New image-settings libraries include sixteen editable presets: Anima / Prefect Anima and
Illustrious XL for all eight image tasks. Each preset already pins its base workflow and
task-specific prompt rules; six tasks per family also pin an optional img2img variant.
The library contains twenty-eight matching saved workflow versions. No provider or task
assignment is enabled automatically. Existing custom/legacy libraries remain intact; use
**Add standard presets · Anima + Illustrious** to add missing entries without replacing
edits. Explicitly deleted libraries stay empty. Capacity errors leave the draft unchanged.

Anima uses a separate diffusion model, Qwen text encoder and VAE. Illustrious uses a
combined checkpoint and its embedded encoder/VAE. Required filenames are the upstream
template defaults, not a claim that these files are installed on every server. Install
the matching files or select your installed compatible files in the workflow editor.
Reference variants are img2img; identity fidelity still needs separate live validation.

## Test inventory

The application currently defines **eight image tasks** in `backend/core/comfyui_task_templates.py`:

| Task | Intended result | Current starter size, SD 1.5 | Current starter size, other families |
| --- | --- | --- | --- |
| NPC portrait | One identifiable NPC; clothing and appearance retained | 408 × 512 | 816 × 1024 |
| Hero portrait | One identifiable protagonist | 408 × 512 | 816 × 1024 |
| Account avatar | Centered single face; check square UI cropping explicitly | 408 × 512 | 816 × 1024 |
| Inventory item | One isolated, readable object; no wearer, hands or UI | 512 × 512 | 1024 × 1024 |
| Location background | Wide environment; no invented cast | 512 × 288 | 1024 × 576 |
| Story illustration | Correct cast, actions and spatial relationships | 512 × 288 | 1024 × 576 |
| Adventure cover | Wide composition without generated lettering | 512 × 256 | 1024 × 512 |
| Style preview | Balanced square composition | 512 × 512 | 1024 × 1024 |

Sizes above are generated starter defaults, not the upload limits or a guarantee of the final provider output. Runtime quality profiles, requested dimensions, alignment and output resizing must also be checked through the application.

Ten supported template families: SD 1.5, SDXL, Pony V6 XL, Illustrious XL, Animagine XL 4.0, FLUX.1 Dev, SD3.5 Large, Anima / Prefect Anima, Nova Anime AM, Qwen Image. Eight base workflows per family make **80 base cases**. Reference img2img is offered for six tasks per family, adding **60 reference cases**. Avatar and style preview have no reference variant. This is a coverage inventory; only families actually installed on the server can receive a live verdict.

## Execution order

1. **Server preflight:** record ComfyUI version, `/object_info`, available loader file choices, supported samplers/schedulers and custom nodes. Identify each installed checkpoint's actual architecture and embedded CLIP/VAE from its documentation and execution, not its filename. Do not substitute the first available file automatically.
2. **Loader variants:** check embedded CLIP/VAE, external encoders/VAE and diffusion-model loaders where the chosen checkpoint supports them. A deliberately missing file or node should produce a useful diagnostic before generation. Verify renamed local files can be selected without editing the graph by hand.
3. **Graph acceptance:** materialize the exact built-in task preset, bind its prompt, negative prompt, dimensions, seed and reference input, then validate/execute it on the server. Record rejected node/input details. FLUX's zeroed negative conditioning is deliberate; a negative binding must not be invented.
4. **Application path:** repeat through TaleWeaver's normal task and test-image flows, including a saved session using current settings versus its saved preset. Verify family-specific prompt rules, prefix/suffix and task composition actually reach the intended text encoders. A raw graph run alone does not test prompt preparation.
5. **Dimensions and framing:** compare requested size, rendered graph inputs, actual output size/aspect and the application's stored asset and displayed crop. Test ordinary and high-resolution generation plus reference resizing. Account avatars need an explicit square-display crop check rather than being assumed correct because a portrait generated successfully.
6. **Quality:** use fixed scenes and seeds where supported, retain outputs, and assess each task against the table above. Check character identity/count, object completeness, background occupancy, anatomy, scene geometry, legible silhouettes and unwanted lettering. Apply model-author recommendations to exact checkpoint versions; derivative/Turbo/Edit/GGUF variants need their own verdict.
7. **First-run rehearsal:** use fresh user settings and a fresh session. Select the installed family/components using the ordinary UI, create task presets, assign them and generate each asset without manual node repair. Repeat after restart and export/import. Record every required setup step and remove avoidable ones.

For each executed case retain: family and exact checkpoint, loader recipe and component files, task and reference mode, preset/workflow hash, final positive/negative text, requested/actual size, sampler/steps/CFG/seed, elapsed time, output and pass/fail notes. Keep **not installed**, **graph rejected**, **generation failed**, **quality failed** and **passed** distinct. No paid Pod time is needed to build the local inventory; live jobs start after the server is available.

## Findings from this run

- **Bindings and components:** the four checkpoint configurations executed through TaleWeaver's native ComfyUI client. The three combined SD checkpoints used embedded CLIP/VAE; Nova used its separate Qwen encoder and Qwen-image VAE. Files initially placed in the diffusion-model directory had to be moved to the checkpoint directory by the server owner.
- **Coverage:** 32 ordinary task cases, 24 same-image img2img reference cases, four runtime-resolution cases, three larger background cases, eight additional Nova scene/garment cases and six WAI Gothic/Cyberpunk cases. The reference test checks the upload/encode/generate path, not identity fidelity under major pose or clothing changes.
- **Dimensions:** outputs followed mapped sizes and alignment, including 1600 × 896 larger backgrounds. SD 1.5's starter preview is 408 × 512 for portraits, while the ordinary runtime profile can request 816 × 1024. This difference must be accounted for when judging its quality. The current ordinary graph does not automatically become a two-pass Hires workflow merely because the requested resolution increases.
- **Framing correction:** new NPC and protagonist templates now share waist-up framing. Their prepared prompts carry a deterministic framing suffix. Shared portrait source instructions also use this framing, avoiding the previous chest-up/waist-up disagreement. The legacy background prompt now asks for 16:9, matching the actual landscape dimensions rather than the former 3:2 text.
- **Garment correction:** task instructions explicitly preserve item count, fabric, cut and proportions, and distinguish a garment from its wearer. A logical matching pair remains a pair. These instructions improve the contract but cannot certify image contents: the live run still produced duplicates and unwanted people despite negative prompts.
- **Sampler experiment:** WAI coat trials kept prompt, seed, size, CFG and steps fixed while comparing Euler a/normal, DPM++ 2M/Karras and DPM++ 2M SDE/Karras. All retained the unwanted second coat. Counterfeit separately compared ordinary settings, the source example's configuration and the owner's UniPC/CFG 6.5/20-step/CLIP-skip-2 configuration. A single seed is insufficient to declare a universal winner.
- **Author resources:** Counterfeit's source example uses EasyNegativeV2 and an Anime6B model upscaler with a second diffusion pass. Both resources were initially absent. Later tests used the supplied RealESRGAN model and, after installation, EasyNegativeV2. Base images, latent-upscale tests and model-upscale/embedding tests were retained separately. These optional resources must be advertised and checked; a filename alone does not establish their presence.
- **Decorative cards:** baking borders into the diffusion prompt produced invented lettering, duplicates and ornament leaking into the garment. Prefer a reusable interface frame with real item text and a separately generated subject/background. The owner's reference distinguishes Anime, Gothic and realistic presentation; Cyberpunk can use the same structure. Frames were explored as artwork in this test, not implemented as a released UI feature.

Checkpoint references: [Counterfeit V3, version 57618](https://civitai.com/models/4468/counterfeit-v30?modelVersionId=57618), [WAI Illustrious](https://civitai.com/models/827184/wai-nsfw-illustrious-sdxl). WAI's author recommends a short quality prefix, restrained negative prompts, Euler a, CFG 5–7, 15–30 steps for v17 and a Hires stage for final detail. Do not transfer those settings indiscriminately to other model families.
