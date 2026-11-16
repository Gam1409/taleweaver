# Portrait composition and regeneration

NPC and protagonist prompts request exactly one subject, waist-up framing with the entire head visible, a
clearly visible face, a simple background, and no lettering or multiple views.
The ComfyUI prompt adapter receives this composition alongside the character
facts, including when prompt adaptation is disabled. Model-specific prompt rules
still determine tags versus prose. Dimensions remain controlled by the workflow
bindings and image settings, not numbers inside the prompt.

In a session NPC card, expand **Portrait regeneration options**:

- **Fix an unsuccessful image / new portrait** defaults to no reference.
- **Change expression, action or setting** selects the previous portrait as a
  reference when one exists. The checkbox can be overridden independently.
- **Requested change** is optional and applies to the portrait only; it does not
  alter the NPC's biography, inventory or game state.

References currently require ComfyUI and a configured image/reference workflow
for the NPC's effective image profile (including the story's saved preset).
The backend selects the current image from the owned session; clients cannot
supply an arbitrary reference URL. Missing references, unsupported providers,
missing workflows or unreadable images fail explicitly rather than silently
falling back to text-to-image. The old portrait remains until generation succeeds.
Automatic first portraits do not use a reference.

Session portraits with a managed appearance profile include confirmed current
visible conditions of the NPC and its worn clothing. This uses the same physical
condition projection as scene illustrations: the latest visible state supersedes
original descriptions and previous images. Facts stay bound to their character or
garment; repairing an item replaces the earlier damage in subsequent portraits.

Public facts alone do not establish visible detail. Private, resolved, unverified
or unavailable-source conditions are omitted, as are traces hidden by current
clothing and conditions of carried or removed garments. Existing records without
confirmed visual evidence remain saved without being inferred into an image.
Reading these facts does not change state or add an extraction request. Historical
scene illustrations continue to use their frozen message-time facts.

The image is uploaded through the existing ComfyUI image binding. The selected
workflow decides how to use it: plain img2img, compatible IP-Adapter/FaceID, or
another image-conditioning pipeline. No custom nodes are inserted automatically.
IP-Adapter and face-specific adapters can improve identity consistency; ControlNet
can guide pose/composition. Their nodes and model weights must match the image
model family. Plain img2img and prompt instructions do not guarantee the same face.

## Scope and verification

The current composition comes from `PORTRAIT_COMPOSITION_INSTRUCTION` and the
NPC/hero task templates. It is a request to the model, not a checked pixel boundary.
Later experiments with a tighter crop, expression/outfit editing, full sprites and
multi-character scene references remain separate from main. They do not provide
an automatic character asset pipeline or checkpoint-independent identity guarantee.

Host tests cover reference ownership, profile/workflow selection, latest confirmed
visible state, conflicts and failed-generation preservation. Actual image quality,
head/hair inclusion and identity retention require visual checks with the chosen
checkpoint and workflow. No new live generation was performed for this docs review.
