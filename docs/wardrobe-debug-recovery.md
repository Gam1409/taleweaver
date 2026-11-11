# Correcting NPC clothing and item placement

Debug > NPCs > Clothing separates three states. Only worn garments appear in
clothing layers. Carried clothes appear in the inventory list. Loose clothing
appears in the room list, with its physical position. Body-placed ordinary items
have their own section; they do not become garments.

Take off keeps the existing item in the NPC's inventory. Put on uses a carried
garment or an available garment in the current room. Place in room asks for a
position and uses the existing world-item drop mechanism. The object keeps its
ID, image and metadata, is removed from wear and carried inventory, and retains
`property_owner_id` as its owner. Moving the NPC does not move that room object.
Taking it back into inventory or wearing it reuses the same object. Other NPCs'
carried possessions cannot be acquired through the room picker.

These are explicit debug corrections, without inference or simulation-clock
advancement. They affect this session, not the adventure template. Editing a
garment's metadata and changing where it is remain separate operations.

## Restoring missing records from text

Restore clothing & placed items from history prepares a reviewable proposal from
the existing bounded window: at most 80 recent story messages and 48,000 source
characters, further reduced only by complete messages if the payload needs room.
It can create missing garments, restore wear for existing IDs, and register an
ordinary object explicitly placed in a body slot. It cannot silently reconstruct
an arbitrary older history outside that window or treat a fluid/body part as an
inventory object.

**What to look for (optional)** supplies a short search hint, such as an item name.
It prioritizes that item in the same model request; it does not establish that the
item exists or bypass evidence checks. A missing ordinary physical object can use
the new-item branch; an anatomical part is not a separate inventory object.

Player descriptions may be proposed in this explicit debug workflow. Their
source is visibly labelled, and applying player-sourced entries requires explicit
selection; the older apply-all command is rejected for those previews. The normal
RP extraction still requires completed narrator evidence. Ownership, exact quotes,
age and body-availability checks remain in effect, and later removals/transfers
must be considered before proposing restoration.

The stored source retains its real role. Body placement is bound to the original
message and hash so the NPC card can display a confirmed occupied slot after reload.
Changed sources invalidate that displayed proof. Rejected body proposals have an
exact-quote correction form. Previews and quote corrections do not apply state;
the user must select and restore the validated entries.

An exact quote proves only that the words occur in a source message. It does not
prove that the quote supports the proposed item, character or current state.
Both accepted and rejected proposals can be corrected before applying. Expand
**Check source / correct this proposal**, select a source message from the same
reviewed window and copy the appropriate exact passage. Confirm the state and
validate the correction, then select the item for restoration. The correction
refreshes the preview token and rechecks evidence, ownership, chronology fingerprint
and clothing policy without another model request or an inventory change. Other
accepted entries must remain unchanged. Unsupported items should stay unselected;
formal validation is not a guarantee of semantic correctness.
