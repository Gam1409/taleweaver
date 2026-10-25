# Character appearance and clothing: proposed next stage

Status: design agreed during the NPC-card work; not implemented by that change.

## One source of truth

The narrator, player sheet, portraits and scene illustrations should read a shared
character appearance and worn-clothing state. Describe appearance separately from
clothing so that removing a coat does not require rewriting a whole biography.
Stable item IDs determine ownership; descriptions never create transferable items.

Keep the existing mechanical equipment slots compatible. A layered worn view can
reference the same owned items without replacing a single equipment slot with an
array or duplicating armor bonuses. Removing a garment does not delete it: it stays
owned until explicitly placed, transferred, consumed or otherwise resolved.
Transfers and deletion must clear the former owner's worn reference atomically.

## Detail preference

A world-creation preference controls clothing detail independently of the NPC-card
indicator toggle:

- Off: general descriptions of visible clothing, without detailed intimate layers.
- On: detailed garment layers, including underwear for explicitly adult characters.

Missing settings in old worlds default to off. A detail setting does not establish
any character's age; unknown or conflicting age information cannot enable adult-only
fields. Any private intimate state remains separate from visible appearance and is
excluded from NPC cards, public session payloads and image-generation input.

The player can see their own worn clothing. An NPC card continues to expose only
information learned through play, never a live private wardrobe or inventory.

## Visible clothing

Garment metadata needs bounded body coverage, layer and opaque coverage. The visual
projector selects exposed surfaces by region: a closed coat can hide a shirt, which
can hide another layer. Removing the coat exposes the shirt, not every lower layer.
Partially open garments require explicit coverage changes rather than guessed
transparency. Unknown coverage should be handled conservatively.

Project visible appearance before image preparation, and freeze that result with
the scene snapshot. A prompt instruction alone is insufficient: raw narration,
character descriptions and old journal entries can otherwise reintroduce hidden
garments. Portraits and scene illustrations must use the same visibility rules.
This improves continuity but cannot guarantee that every image model follows a prompt.

## Integration and verification

Integration spans manifest application, Avatar and WorldEntity storage, equipment
and transfer handling, the existing continuity pass, player-sheet rendering,
portrait preparation, scene snapshots and save/import/clone/checkpoint handling.
Prefer bounded additions to existing model calls over another call for each garment.

Verify layer occlusion, partial coverage, ownership and transfer invariants, failed
or ambiguous actions, private-field exclusion, old-save compatibility, historical
snapshot stability and concurrent image generation. Both actual provider request
payloads and public API responses must be tested for hidden-clothing leakage.
