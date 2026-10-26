# Character appearance and clothing

VN characters can retain a neutral appearance profile and clothing linked to canonical
inventory items. Hair, eyes, build and distinguishing features are separate from worn
clothes. Existing RPG equipment slots and stat bonuses remain unchanged.

## Creating a world

The VN creation form has a separate **Adult content: detailed clothing** preference:

- Off (default): track general outer clothing and accessories.
- On: track garment details and layers, including ordinary underwear only for a
  character whose structured age explicitly establishes adulthood.

The preference is independent of NPC-card indicators. It does not establish age or
enable arousal mechanics. Old worlds without the preference default to off.

Generated outfits should suit each character's circumstances, personality, setting,
profession and weather. There is no uniform default kit. Clothing uses the same
canonical object registry as other possessions; with a small object budget, required
story objects take priority and some clothing may remain unstructured descriptions.
The implementation does not silently add an unlimited wardrobe to every character.

## Changes during play

The existing VN continuity call can propose bounded wardrobe changes using current
item IDs and quoted evidence. Removing clothing retains ownership. Gifts transfer
through the existing inventory mechanism and do not automatically equip the recipient.
An NPC can choose to change clothes when the scene and their agency support it.

A genuinely new cosmetic garment requires a grounded acquisition: an accessible
wardrobe, established shop or giver, or crafting with consumed owned materials.
The server assigns its ID and tracks the result. Existing possessions must be
transferred rather than recreated. These operations cannot mint money, armor bonuses
or combat statistics. Plans, claims and hypothetical events are not completed actions.

Ownership, references, scene, source, permitted operations and duplicate requests are
checked in code. Recognizing the meaning of a sentence and whether the situation
justifies an acquisition still depends on the technical model. An exact quotation
alone cannot prove that the model interpreted tense, negation or character choice
correctly. Small models should be tested with the intended story and language.

## Editing an existing adventure

In a VN adventure editor, open **World → Narrative Blueprint** and use
**Adult content: detailed clothing**, then **Save clothing settings**.
Enabling prepares missing visual profiles through the Small/Utility model using
known descriptions and already owned items. Existing valid profiles are retained;
unknown facts stay unspecified, and the conversion does not invent possessions.
Preparation is bounded to four minutes. A model error, invalid references or a
concurrent edit prevents the save; reload or retry after correcting the model settings.

Disabling deactivates detailed tracking without deleting inventory, profiles or
character history, so re-enabling does not reset the wardrobe. Switching away from
VN also disables this preference. The editor changes the adventure template and
future games; existing saved sessions retain their own settings and state.

## Cards and images

The player's VN sheet has an **Appearance** tab showing their own tracked outfit.
Detailed adult clothing can include the player's covered layers. NPC cards never
expose a private wardrobe or inventory. A missing profile shows an empty state;
it does not invent a standard outfit or imply that the character is undressed.

Image preparation resolves layers by body region. Higher opaque clothing hides lower
layers; an explicitly open garment can expose only its specified uncovered regions.
Portraits and frozen scene snapshots use this same visible projection. Invalid or
unknown coverage is handled conservatively. Managed image prompts do not reuse raw
biography, old wardrobe descriptions or journal entries as outfit instructions.

A manual illustration of a managed scene extracts a bounded final composition before
model-specific prompt formatting. The two Small-model operations share one preparation
timeout. This additional operation is not performed on every gameplay turn. Managed
portrait pose/expression edits also use bounded extraction. Image models and img2img
references can still fail to follow the current outfit; this is not identity or pose
control and does not require custom ComfyUI nodes.

## Persistence and compatibility

Nullable `visual_profile` JSON columns store Avatar and authored NPC profiles. NPC
runtime changes live in session overrides. Canonical items carry `clothing` metadata;
profiles reference their IDs. ADV/ADS export, import, session start/copy and checkpoints
preserve the tracked state. The Alembic migration is `353aa8ad41f8`.

Legacy worlds without structured profiles retain their existing rendering path. A
specific garment already described as currently worn can be registered during play;
missing age, anatomy or hidden clothes are not inferred. Existing saves are not
rewritten into a fabricated wardrobe.
