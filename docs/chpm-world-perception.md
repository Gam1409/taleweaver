# CHPM observer-local world perception

The live host adapter now captures authoritative state at the saved player-input
boundary, after source reconciliation and before cognitive proposals. It exposes
the selected observer's scene, visible co-present NPC IDs, own possessions
(canonical IDs and short names) and known worn item IDs. It reads session overrides
before authored defaults. Unknown inventory/profile data remain unknown. Invalid
or stale worn references cannot establish undressing. Other inventories, hidden
or absent NPCs, nested container contents, private thoughts and arbitrary narrator
prose are not read as witnessed facts.

The initial frame establishes a baseline. Later frames can add one aggregate
world-difference source: own scene changed, an own possession appeared/disappeared,
known worn IDs changed, or an actor became visible/no longer visible in the same
scene. When the observer changes scene, differences in the visible cast do not
claim that other NPCs moved. No difference establishes who caused it, why, whether
an absent character departed or died, or whether an item was gifted versus stolen.
Only differences between observations are known; intervening events can be missed.

Frames and differences are separate witnessed sources. Player and reviewed NPC
speech remain reports. Old frames are historical, never replacements for the
current frame. Each source is anchored to the saved input's ID/revision/hash and
commits with the reviewed reply. Reconciliation, rewind, archive rollover and
session copying preserve their provenance. No extra inference call is added.

Display text is valid JSON bounded to 2,000 characters with explicit omitted-list
counts. The full typed frame remains stored for subsequent comparison and source
hashing. Bounds are 128 visible NPC IDs, 256 own item records and 32 worn IDs;
oversized frames fail explicitly rather than silently truncating canonical facts.
Missing fields in legacy frames bootstrap the new baseline without inventing a
past inventory. Legacy source hashes remain compatible.

Appraisal can cite exposed differences as witnessed evidence. The motive catalogue
labels them `world_observation`, distinct from reported claims and subjective
beliefs. They cannot replace the required supporting personal identity/agenda
motive. This remains dialogue-intention selection, not execution of world actions.

Tests cover own-state filtering, unknown clothing, omitted lists, same-scene versus
observer movement, bootstrap, exact hashing, current-frame selection, rollback,
and real VN publication with mock cognition. A correct host difference does not
prove the LLM's interpretation is psychologically or semantically correct.
