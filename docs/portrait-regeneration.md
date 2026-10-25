# Portrait composition and regeneration

NPC and protagonist prompts request exactly one subject, chest-up framing, a
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

The image is uploaded through the existing ComfyUI image binding. The selected
workflow decides how to use it: plain img2img, compatible IP-Adapter/FaceID, or
another image-conditioning pipeline. No custom nodes are inserted automatically.
IP-Adapter and face-specific adapters can improve identity consistency; ControlNet
can guide pose/composition. Their nodes and model weights must match the image
model family. Plain img2img and prompt instructions do not guarantee the same face.
