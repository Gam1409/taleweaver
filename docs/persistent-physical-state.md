# Persistent physical state (first implementation)

VN sessions now keep a small physical condition ledger alongside their existing world state. An injury, dirt on an item, fluid trace, pain or another explicitly described condition survives an unmentioned turn, a location change and a page reload. A model omission does not resolve a recorded condition.

This is a state ledger, not a medical simulator or a complete causal world model. It does not infer diagnoses, pregnancy, quantities, elapsed healing, emotions or changes to personality. Clothing ownership and placement continue to use the existing clothing system; item descriptions remain intrinsic descriptions rather than condition summaries.

## How a completed turn changes state

1. The existing post-narration item reconciliation request also receives relevant active physical facts and an optional `condition_updates` field. There is no additional model request.
2. The model proposes a new fact or an operation on a known condition ID. The host checks the schema, available canonical subject, operation/kind compatibility and an exact contiguous quote from the completed assistant narration. Player requests and earlier history are not evidence for this pass.
3. After the assistant reply has a saved ID, accepted changes are stored with its ID, content hash and quote in the same final turn transaction. The host assigns condition IDs. One rejected condition candidate does not cancel other valid candidates or a valid item action.
4. The next continuity request receives current facts for available actors, their known items and accessible loose items. The narrator receives public facts for actors, visible garments and visible scene items, plus the player's own conditions, constrained by clothing and perspective. CHPM receives each NPC's own private physical conditions in its actor context.

A valid quote proves that the words occur in the reply. It does **not** prove that the model correctly understood the actor, body region, extent, actuality or completeness of the action. This implementation reduces forgotten recorded facts; it does not guarantee extraction completeness or semantic correctness. Live evaluation with the user's model remains necessary.

| Operation | Result |
| --- | --- |
| `record` | Register a new fact for a canonical actor or known item. Private by default. |
| `change` | Correct the description/visibility of an existing active fact. Keep its status. |
| `treat` | Mark an injury or pain as treated. Keep the condition. |
| `reduce` | Keep a reduced but still present condition. |
| `clean` | Resolve contamination or fluid explicitly removed from that subject/part. |
| `heal` | Resolve an explicitly healed injury or pain. |
| `remove` | Resolve explicitly removed contamination, fluid or another non-injury condition. |

Disinfection or stitching is treatment, not complete healing. Wiping one surface does not establish that another internal region is empty. Washing one coat cannot change a different coat's record. A repeated event after resolution requires a new record. Active facts with the same subject, kind and part must be updated using their existing ID rather than rephrased as duplicates.

## Debug → State

The unified debug inspector has a **State** tab containing:

- active conditions, optional recent resolved conditions, canonical subject, body part/item area, status and visibility;
- the latest source quote and message ID; manually entered corrections are clearly marked;
- the last reconciliation failure or rejected operations;
- a manual record/correction form, including treatment, reduction, cleaning and healing.

Manual edits use the existing owned-session debug command pipeline and session mutation lease. They require debug mode and the currently viewed ledger revision; a stale form cannot overwrite a newer ledger. They do not call a model, advance story time, alter inventory or change NPC personality.

Existing sessions start with an empty ledger. Old narration is **not** automatically rescanned. Use the manual form to establish an older condition that is still present. Debug's legacy HP healing command does not resolve narrative injuries; resolve these explicitly in **State**.

## Persistence, privacy and failures

Storage is the additive `entity_states.__physical_conditions__` JSON record (`version: 1`); no database migration is needed. Full-turn regeneration rewinds the ledger with the turn snapshot. Narration-only rewriting keeps world state, as it does for inventory and locations. Session copying and `.ads` export/import preserve facts and remap source message IDs. If the source message was not included, it is marked unavailable rather than silently dropping the fact or claiming a different message established it.

Source quotes and hashes describe the completed reply at registration. A later narration-only rewrite can change the displayed wording; it does not retroactively remove the physical fact or replace its recorded evidence.

A missing, timed-out or invalid shared model response preserves existing conditions and records a failed check; the completed story reply can still be published. Invalid optional condition candidates are audited independently. Invalid stored ledger data is preserved and reported rather than replaced with an empty ledger.

The narrator projection excludes another NPC's private conditions and hidden inventory items. A public fact still does not establish exposed skin, immediate visibility or another NPC's knowledge. CHPM gets an NPC's own bodily conditions, not another NPC's private state. These restrictions cannot prevent a model from repeating a fact already present elsewhere in the supplied story history.

## Bounds and current limits

- At most 12 condition proposals per completed reply.
- At most 512 active conditions across the session. New records are rejected visibly at capacity; existing facts are never evicted to make room. Resolving existing conditions remains possible.
- The recent inspector retains 64 resolved records and 128 operation events. Older closed records/events are removed from this recent view with explicit counters; original narration stays in chat history. This is not an unbounded audit archive.
- Detail is limited to 320 characters; body part/item area to 80; evidence to 600. Context grows with relevant active facts, not the full sequence of previous changes. Existing reconciliation context/deadline guards remain in force.
- Automatic extraction covers available actors and known items from the completed turn's current possession context. It does not simulate off-screen actors, infer room-wide contamination or attach a condition to an item whose canonical ID will only be created by that same reply.
- Private body conditions can guide CHPM decisions. The narrator's public projection intentionally does not reveal a private condition just to remind the reader every turn.

Tests cover literal evidence, independent rejection, treatment versus healing, partial removal, subject scoping, capacity and retention, private projections, saved VN turns and the unchanged request count, failed shared extraction, full-turn replay, manual debug revision guards, real copy/export/import, and the debug form in desktop/mobile browsers. Model understanding still needs separate live tests.
