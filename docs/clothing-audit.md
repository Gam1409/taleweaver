# Clothing integration audit

The VN clothing pipeline is connected: the continuity request receives `clothing_context`
and structured wardrobe action schemas, accepted actions update state, narration is rebuilt
after wardrobe changes, and image composition uses saved appearance and visible clothing.
This audit did not call a live LLM or inspect a particular player's saved session.

## Findings

### Wearable editor items can lack wardrobe metadata — editor workflow corrected

`ItemDraft` in `backend/api/routes/adventures/editing/item_generation.py` produces a type,
portability and equipment slots, but no `clothing` metadata. The ordinary editor also allows
WEARABLE objects with only slots. `garment_for_item()` needs layer and coverage data;
`_change_wear()` ultimately calls `validate_profile()`, which rejects such an item with
`Worn items require valid garment metadata.`

Reproduction: create a WEARABLE coat with a Chest slot, put it in an actor's owned inventory,
and submit a wear action. The object is a valid inventory/equipment item, but cannot be worn
through the structured wardrobe subsystem without garment metadata. This affects the new
item draft feature as well as manually authored legacy items.

Implemented correction: wearable drafts now require validated garment metadata, and the item
editor exposes category, layer, regions and lower-layer occlusion. **Prepare missing clothing
data** proposes missing properties without overwriting existing ones or saving automatically.
The saved metadata feeds wardrobe actions and visible appearance. Accessories never occlude
whole body regions, but can themselves be hidden under a higher opaque garment. Existing
unprepared items still need review and saving; ownership does not imply wearing.

### Empty converted profiles can suppress previously described outfits

`editor_conversion._validate_actor()` accepts an empty appearance and worn list. Conversion
saves that as a valid `visual_profile` even when the old biography describes clothing but
there are no owned clothing objects to reference. `character_visuals()` treats the profile
as managed, and `_NarratedNPC` replaces the original description with the empty projection.
The coat described in the biography is then absent from current visible clothing context.

The same saved profile prevents `established_wear`: `_creation_source_valid()` requires
that no profile exists. Subsequent editor conversion skips actors with valid profiles.
This can strand a character between legacy descriptive clothing and tracked clothing.

Reproduction: convert an actor described as wearing a white coat, with no inventory items,
using an empty `PreparedActor`. The resulting valid profile has no worn items; narrated
visual description omits the white coat and no longer qualifies for legacy initialization.

Recommended correction: distinguish uninitialized clothing from a deliberately empty worn
list. Preserve known legacy visible facts until initialization succeeds. Never restore an
old outfit over an intentional removal or invent ownership/garments without reviewed evidence.

## Operational constraints

- Detailed clothing is a preference, not an on/off switch for all outer clothing tracking.
- Editing template preferences does not retroactively alter an existing session's frozen
  snapshot. Investigate the session's own settings and actor profiles.
- World generation may omit structured clothing when canonical objects cannot fit the
  requested object budget. It is not guaranteed for every generated NPC.
- The continuity model must emit wardrobe actions; prose alone does not update clothing.
  Rejected actions are explained to narration through the internal clothing resolution.
- Saved clothing takes precedence over contradictory prose in image generation. A stale
  clothing state can therefore consistently produce a stale outfit in illustrations.

## Validation

The existing clothing, movement and presentation regression selection passed 145 tests.
Separate deterministic reproductions confirmed both findings above. Passing tests establish
that covered pipeline paths work, not that a particular model obeys the prompts or that all
editor-to-game clothing workflows are complete. No clothing prompts or behavior were changed
as part of the initial audit; the editor correction above was implemented subsequently.
