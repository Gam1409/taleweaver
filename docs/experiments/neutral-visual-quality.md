# Neutral visual quality experiment

Status: implementation and mocked regression verification only. No live image-quality
claim. Source-rich context is now the default; no environment setting is required. This path is for
non-graphic illustrations. The single preparation path is independent of the adventure's
content setting; existing profile/adventure addendum gates still apply.
The source-mode instructions still request non-graphic illustrations, so forwarding
an addendum does not remove that restriction. Adult-content prompt files were not changed.

## Evidence and limits

- [Better Captions / DALL-E 3](https://cdn.openai.com/papers/dall-e-3.pdf): detailed,
  accurate training captions improve prompt following. This supports retaining useful
  facts, not a claim that arbitrarily long runtime prompts always perform better.
- [Lost in the Middle](https://arxiv.org/abs/2307.03172): relevant-information position
  matters in long-context retrieval. This is text-task evidence, not an Artemis image
  benchmark. Supply the current completed passage, not the entire conversation.
- [GenEval](https://arxiv.org/abs/2310.11513) and
  [T2I-CompBench](https://arxiv.org/abs/2307.06350): evaluate counts, attributes and
  relationships independently of aesthetics. A beautiful picture can still fail.
- [Scene Graphs](https://arxiv.org/abs/1804.01622): explicit relationships help in a
  system that actually conditions layout on them. A small JSON enum followed by a
  prose LLM is not equivalent to bounding boxes or segmentation conditioning.
- [ComfyUI basic guide](https://docs.comfy.org/tutorials/basic/text-to-image): its
  SD1.5 example uses phrase/tag prompting and explains conditioning nodes.
- [Official FLUX.2 guide](https://docs.bfl.ai/guides/prompting_guide_flux2): describes
  subject/action/style/context, important facts first, natural language or structured
  JSON, and no negative prompts for FLUX.2. These model-specific rules must not be
  generalized to every FLUX variant, SDXL or Anima. Existing checkpoint policies remain
  responsible for formatting; this experiment does not change workflow graphs.

Sources read on 2026-10-30. The combined approach is an engineering hypothesis to
validate, not a result already demonstrated by these publications on TaleWeaver.

## Data path

`hash-verified completed message + message-time public snapshot`
→ remove sound/pause cues, retain emotional labels
→ one Utility LLM call with source and canonical state together
→ existing checkpoint formatting, prefix/suffix and workflow mapping
→ ComfyUI

The source is not replaced with an enum frame. It includes the full
verified message, even if the historical snapshot kept only its final 16,000 chars.
More than 48,000 cleaned characters fails explicitly; no truncation or retry loop is
used. This bound is not a token-limit guarantee. The configured LLM context still
needs to accommodate instructions, state and completion.

Canonical state controls wardrobe/identity/ownership; the passage supplies current
visible action, chronology, environmental details and lighting. Missing clothing is
unknown. The LLM is instructed to avoid inventing gestures, possessions or extra
people and to keep the output non-graphic. This is instruction-based interpretation,
not a formal proof that every returned fact is correct. No game state is changed.

Query continues to capture the actual LLM request/response. Image details records
`context_mode=neutral_source` for newly generated illustrations; older metadata stays readable.

## Use

Restart the backend after updating. There is one scene-illustration preparation path,
with no environment selector. The former `VISUAL_SCENE_CONTEXT_MODE` setting is removed.
Use a neutral VN adventure and an existing valid ComfyUI workflow and checkpoint policy
for evaluation. A legacy comparison requires a separate checkout of the earlier version.
Portrait-specific frame extraction remains in use and is not removed by this change.

## Evaluation protocol

Use the eight synthetic cases in `neutral-visual-cases.json`. They include state
conflicts, an entering character, a departure, props, distinct wardrobe colors,
hypothetical events and an unspecified pose. The candidate cast is not a requirement
to show every candidate. Preserve the same message-time facts across both modes.

For each case and mode:

1. Record model/version, chat template, sampling parameters, context size and request
   timeout. Use the same LLM settings; repeat each prompt preparation three times.
2. First score the resulting prompt against each required/forbidden fact. Mark a fact
   preserved, omitted, contradicted or invented. Inspect Query rather than assuming
   a successful API call establishes correctness.
3. Generate images from each candidate prompt with the same workflow, checkpoint,
   sampler, scheduler, steps, guidance, resolution and three paired fixed seeds. Equal
   seeds reduce one source of variation; they do not guarantee deterministic GPU output.
4. Blind the mode label when reviewing images. Score cast count, per-person clothing,
   action, spatial relation, props and lighting independently. Mark unknown pose as
   not applicable rather than inventing a reference answer. Score aesthetics separately.
5. Record request failures, durations and prompt lengths, but do not select the faster
   method at the expense of fidelity. Keep references disabled for the first comparison;
   repeat with the same reference later to isolate reference influence.

Eight cases × two modes × three prompt samples × three image seeds = 144 images.
This is a small pilot, not a statistically conclusive benchmark. Run a smaller smoke
check first to catch configuration errors before spending GPU time on the full pilot.

Investigate and fix any case where the path swaps identities/wardrobes, invents
possessions, corrupts session state, exposes private inventory, or fails provider
compatibility. Assess prompt-level omissions and image-level accuracy across the
tested model families. Document model-specific
failures instead of adding a universal workaround to every checkpoint.

No live KoboldCPP/ComfyUI endpoints were used during implementation. That part
of validation remains outstanding; passing mocks establishes wiring, not image quality.
