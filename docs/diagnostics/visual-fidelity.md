# Visual prompt fidelity

This investigation covers neutral visual continuity: visible cast, clothing, pose,
position, lighting and the final moment of a completed passage. It does not change
adult-content prompt text or content policy. It uses the existing Utility model.

## Actual pipeline

1. `scene_illustrations/snapshots.py:capture_scene_snapshot` freezes public appearance,
   visible clothing and a bounded passage at message time. Private inventories and
   goals are excluded. At generation time, ownership and the complete message hash
   are checked by `scene_illustrations/context.py:owned_context/require_snapshot`.
2. `scene_illustrations/render.py:image_request` selects the story's image profile,
   style and tone. Without managed clothing, the passage and frozen facts go directly
   to the prompt adapter. With managed clothing, the passage first goes to
   `clothing/frames.py:extract_frame` using the Small/Utility role and its timeout.
3. `VisibleFrame` validates character IDs, bounded enum values and relations.
   `compose_frame` combines these with frozen visible clothing and appearance.
   Free narrative clothing cannot overwrite tracked wardrobe or ownership.
4. `prepare_moment_prompt` calls `image_prompt_adapter.py:adapt_body` once. ComfyUI
   checkpoint policies determine tags, prose or hybrid formatting. Mandatory tokens
   are assembled separately. Disabling checkpoint adaptation still leaves the
   existing moment-to-description step: this is not a raw-passage passthrough switch.
5. `comfyui_images.py:generate_comfy_image` assembles positive/negative prompts,
   resolves dimensions and seed, and renders workflow bindings. `ComfyClient.execute`
   submits the graph, polls history and downloads the selected output. Generation
   details capture the mapped prompt actually sent, not a reconstructed description.
6. `scene_illustrations/generation.py:_attach` uses message-version checks and
   compare-and-swap to attach only to the unchanged reply.

Session portrait regeneration also uses the same bounded frame extractor for
requested changes when managed appearance is available. References remain optional.

## Confirmed code losses and changes

- Both stored passages and direct frame extraction kept the *first* 16,000
  characters. A final departure beyond that boundary was unavailable to the model.
  Both now keep the **last** 16,000 characters. For existing snapshots, generation
  uses the hash-verified original message's ending, preserving frozen appearance.
- Managed frame composition dropped lighting. It now carries frozen lighting.
- An unspecified extracted position replaced a known position. It now falls back
  to the frozen position; an explicit new position still wins.
- An omitted action defaulted to `still`, inventing inactivity. Its default is now
  `unspecified`; explicitly returned `still` remains valid.

Synthetic example: an adult visitor initially holds the nurse's hand, then releases
it and leaves after a long passage. Previously the extraction input could end before
that departure. Now its input contains the departure. If the extractor returns only
NURSE with unspecified position/action, the composed frame keeps the nurse's known
position beside the window and the warm bedside lamp, without asserting inactivity.
This verifies data preparation, not the quality of an actual generated image.

## Remaining limitations

The enum schema deliberately cannot express every observable action. Adding arbitrary
free text would weaken the existing hidden-clothing and identity boundary; this change
does not do that. The 16,000-character suffix can still omit earlier context. Frozen
appearance helps but cannot recover every omitted event.

The adapter previously cut its response at the configured word budget, potentially
removing a final action, position or negation. The word count now guides the LLM only;
valid responses are preserved (including line breaks). Empty or over-12,000-character
responses still fail explicitly, rather than being partially submitted. The new
`prompt.budget` trace records whether the target was exceeded. Text encoders may still
have their own token limits; this does not promise every workflow uses unlimited text.
There is no semantic completeness scorer: a lexical comparison across Russian prose
and English visual tags would produce misleading results. No extra verification LLM
calls or retry loops were introduced.

There is no evidence here that Artemis or KoboldCPP censorship caused a particular
failure. Tests mock model responses and ComfyUI. No live GPU endpoint was exercised.
KoboldCPP's AutoGuess/chat-template configuration is server-side; TaleWeaver passes
OpenAI-compatible role messages and does not select that server template.

## Private local diagnostics

Add to `.env` and restart the backend:

```dotenv
VISUAL_TRACE_ENABLED=true
VISUAL_TRACE_CONTENT_ENABLED=false
```

This records per-stage lengths, hashes and timing to `log/visual-traces/<trace_id>.jsonl`.
The normal system-debug switch does not enable content capture. Both new flags default
to false. Successful moment illustrations show the local trace ID in Generation details.
Failed requests also leave a trace; locate the newest file by modification time.

**Sensitive-content warning:** to inspect actual scene text, prompts and responses,
explicitly set `VISUAL_TRACE_CONTENT_ENABLED=true`. This writes private story content
and character names locally. Use synthetic scenes, protect the directory and never
publish the traces. Configuration headers, API keys, provider URLs, private inventory
and full custom workflow graphs are not passed to this recorder. Text that the user
places inside a scene or custom prompt is still sensitive and is not automatically
anonymized. Leave general `LLM_TELEMETRY_ENABLED=false` if you do not separately need
its broader, independent logging.

Stages include snapshot, frame request/parsed result/composition, prompt request,
LLM response, prompt word budget, ComfyUI mapped inputs, completion/failure. Custom
OpenAI additionally records role messages and schema before the SDK call, and returned
message content before TaleWeaver's text normalization. These are SDK inputs, not a
network packet capture. General LLM response logs may already contain normalized text.
Failure traces record exception types, never exception messages or response bodies.

Comfy traces expose only allowlisted mapped prompt/negative/size/seed inputs. Custom
node parameters and uploaded image bytes are deliberately omitted. Inspect an exported
workflow locally if those need auditing. Trace content is bounded to 100,000 characters
per field and 1 MiB per request; fields mark their truncation. Up to 30 completed/recent
files are retained, with active requests protected from cleanup. Storage failures do
not interrupt generation. Files are outside the HTTP data directory and ignored by Git.

After diagnosis, set both flags to false, restart, then delete files from
`log/visual-traces`. There is no public download/delete endpoint for private traces.

## Manual KoboldCPP comparison

1. Use a synthetic two-adult scene with distinct coats, explicit positions and a final
   withdrawal. Add a second test longer than 16,000 characters with the departure last.
2. Enable both diagnostic flags temporarily; generate one moment illustration.
3. Compare `snapshot` → `frame.parsed` → `frame.composed` → `prompt.budget` →
   `comfy.mapped_inputs`. Distinguish extraction loss, word-budget loss, and workflow
   mapping errors. An absent intermediate stage can identify a failed step.
4. Replay `custom_openai.request` messages and schema against the same KoboldCPP
   `/v1/chat/completions`, using the same model, sampling settings, seed (if supported),
   token limit and server chat template. Supply credentials separately, never in a trace.
   Without identical sampling parameters, different prose alone does not prove a bug.
5. Compare the returned message with `custom_openai.response`. If the final mapped
   prompt is correct but the picture is wrong, investigate checkpoint/workflow/reference
   influence rather than silently modifying story state or adding invented facts.
6. Disable tracing and remove the local traces.

## Verification

The targeted backend run passed 149 tests across visual fidelity, clothing images,
scene illustrations, session portraits, custom OpenAI transport, ComfyUI and presets.
`test_suggestion_uses_manual_profile_and_body_is_not_adapted_twice[False]` was excluded
from that final run after separately confirming the same failure on the original
checkout. Its profile/story preference expectation predates this change; prompt
content and that test were left untouched. Frontend production build and Ruff passed.


## Generation details: Query

New moment illustrations keep up to four LLM exchanges with the image's private
session metadata. The Query view shows system/user prompts and the returned reply,
including scene analysis when used. It works without debug logging and does not read
local trace files. Each text field is capped at 32,000 characters, with a visible
truncation notice; this preview limit does not truncate the actual model input or
image prompt. Older images have no retroactively reconstructed query.

Queries may include private scene text and custom instructions. They are subject to
the same session ownership checks as the illustration, and can travel with an exported
session. No API headers or credentials are captured. Query capture does not change
the prompts or make additional LLM calls.

## Neutral scene context follow-up

The structured frame now includes bounded lighting and explicit character presence
(visible/off-screen/uncertain), plus entering/leaving actions. The extractor is told
to distinguish an actual arrival from footsteps, dialogue mentions or a future visit.
Only visible figures may participate in spatial relations. An unspecified posture is
explicitly unknown, never a reason to invent a standing pose.

Managed NPC snapshots now retain known spatial position. Player/NPC clothing resolves
canonical session item overrides using the existing wardrobe resolver, and NPCs use
the same legacy-inventory fallback as wardrobe logic. Explicit empty inventories stay
empty; the change cannot invent possessions or restore a removed garment. These
snapshot corrections apply to new completed turns. Old snapshots keep their historical
wardrobe data rather than replacing it with today's inventory.

Image preparation removes known sound/pause cues from a copy of the passage before
extraction/adaptation. Emotional markers such as `[angry]`, `[playful]`, `[surprised]`
remain available as context. Story text, speaker attribution and unknown markers stay
intact; chat messages, TTS and persisted history are not modified. This does not make
emotion tags literal text to draw in the image.

81 focused regression tests passed, including lighting/presence, canonical clothing,
voice preservation, portraits and scene illustrations. Model output was mocked; the
schema and data-flow checks do not establish live Artemis accuracy.

## Visual context ownership

`scene_illustrations/visual_context.py` now owns preparation of the frozen source,
request-local copies and composition with a validated frame. `render.py` orchestrates
LLM/provider selection rather than separately assembling the same context twice.
The state authority instruction distinguishes canonical appearance/wardrobe from
extracted visibility/action/lighting. `clothing_detail_limited` is retained in the
composed frame so incomplete wardrobe information cannot appear complete by omission.

This is a behavior-preserving separation of the managed source boundary, with an
uncertainty-propagation fix. It does not forward the entire passage through that
boundary, remove the frame-extraction call, or resolve all semantic losses described
above. Adult-content instructions and their injection are unchanged. 73 targeted
regression tests passed; no live model/image generation was performed for this change.
