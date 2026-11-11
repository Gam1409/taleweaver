# Persistent physical state (first implementation)

VN sessions now keep a small physical condition ledger alongside their existing world state. An injury, dirt on an item, fluid trace, pain or another explicitly described condition survives an unmentioned turn, a location change and a page reload. A model omission does not resolve a recorded condition.

This is a state ledger, not a medical simulator or a complete causal world model. It does not infer diagnoses, pregnancy, quantities, elapsed healing, emotions or changes to personality. Clothing ownership and placement continue to use the existing clothing system; item descriptions remain intrinsic descriptions rather than condition summaries.

## How a completed turn changes state

1. The existing post-narration item reconciliation request also receives relevant active physical facts and an optional `condition_updates` field. There is no additional model request.
2. The model proposes a new fact or an operation on a known condition ID. The host checks the schema, available canonical subject, operation/kind compatibility and an exact contiguous quote from the completed assistant narration. Player requests and earlier history are not evidence for this pass.
3. After the assistant reply has a saved ID, accepted changes are stored with its ID, content hash and quote in the same final turn transaction. The host assigns condition IDs. One rejected condition candidate does not cancel other valid candidates or a valid item action.
4. The next continuity request receives current facts for available actors, their known items and accessible loose items. The narrator receives public facts for actors, visible garments and visible scene items, plus the player's own conditions, constrained by clothing and perspective. Explicit recent resolutions remain as compact negative facts, so old prose cannot silently restore a healed wound or cleaned item.

In live CHPM, bodily conditions and conditions of the NPC's current possessions enter its existing typed host snapshot. They are available through `inspect_self` and citable evidence for cognition. Treatment and explicit resolution produce host differences; a missing/corrupt record or a lost possession never establishes healing. The legacy standalone bodily context is removed when the current host snapshot supplies it, avoiding a duplicate input block. Shadow mode retains its existing input path.

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
- first-recorded and last-changed game minutes, with unknown values for legacy records;
- counts of proposed, applied and unapplied conditions, including successful checks with zero proposals;
- the last reconciliation failure or rejected operations;
- a manual record/correction form, including treatment, reduction, cleaning and healing.

Manual edits use the existing owned-session debug command pipeline and session mutation lease. They require debug mode and the currently viewed ledger revision; a stale form cannot overwrite a newer ledger. They do not call a model, advance story time, alter inventory or change NPC personality.

Schema rejections name the affected field and constraint, for example
`Condition proposal 1: detail: Text must contain at most 320 characters.`
Conflicting operation fields explain the existing-ID or new-record rule. Diagnostics
contain at most five field reasons and omit candidate values and unknown field names.
The extraction schema advertises these operation-dependent requirements as well.
Historical `invalid fields` messages remain readable; their discarded field details
cannot be recovered from that message. No extra model request or automatic correction
is made, and rejected candidates do not replace confirmed facts.

Existing sessions start with an empty ledger. Old narration is **not** automatically rescanned. Use the manual form to establish an older condition that is still present. Debug's legacy HP healing command does not resolve narrative injuries; resolve these explicitly in **State**.

For a manual record, choose the NPC as subject, the condition kind, its specific body
part and current detail. Fluid traces use `fluid`; another explicit physiological sign
can use `other`. Select Public only for facts established as known to the player.
Public manual corrections appear under **Characters > NPC > State > Physical condition**
while that NPC is present. Private or resolved records stay out of that public card.
This works with NPC Personality enabled or disabled. A public correction alone does
not establish exposed skin or a visible surface for image generation.

An internal condition and a visible external trace have separate records when both
are established. Partial cleaning uses `reduce` with the remaining detail; complete
cleaning resolves only the selected record. Wetness and other physiological signs
are physical facts, not automatic evidence of a particular feeling or desire. The
shared extraction can record them from completed narration, but cannot infer an
unwritten bodily consequence or recover an old omission by itself.

The timestamps read the existing authoritative session clock; recording a condition never advances it. `first_recorded_minute` is when the host first registered the fact, not an inferred onset time. `last_changed_minute` changes only on an accepted update. An omitted fact, rejected proposal or repeated check does not refresh either time. Legacy records keep unknown times until an actual change; their original onset is never invented. Full-turn replay restores the historical clock and these fields together; copies and exports preserve them.

A successful extraction with zero proposals is displayed explicitly. It means the model proposed no changes, not that the host proved nothing happened or that an NPC has no physical conditions. A diagnostic-only empty ledger does not become a citable healthy-state observation in CHPM. See [VN time passages](vn-time-passages.md) for explicit multi-day skips and bounded Living World catch-up.

## Persistence, privacy and failures

Storage is the additive `entity_states.__physical_conditions__` JSON record (`version: 1`); no database migration is needed. Full-turn regeneration rewinds the ledger with the turn snapshot. Narration-only rewriting keeps world state, as it does for inventory and locations. Session copying and `.ads` export/import preserve facts and remap source message IDs. If the source message was not included, it is marked unavailable rather than silently dropping the fact or claiming a different message established it.

Source quotes and hashes describe the completed reply at registration. A later narration-only rewrite can change the displayed wording; it does not retroactively remove the physical fact or replace its recorded evidence.

A missing, timed-out or invalid shared model response preserves existing conditions and records a failed check; the completed story reply can still be published. Invalid optional condition candidates are audited independently. Invalid stored ledger data is preserved and reported rather than replaced with an empty ledger.

The narrator projection excludes another NPC's private conditions and hidden inventory items. A public fact still does not establish exposed skin, immediate visibility or another NPC's knowledge. CHPM gets an NPC's own bodily and possession conditions, not another NPC's private state. Ordinary unreviewed fallback does not publish the observer's private bodily snapshot; narration still gets its audience-filtered world-state block. These restrictions cannot prevent a model from repeating a fact already present elsewhere in the supplied story history.

The host snapshot keeps its complete typed view within the ledger's existing limits; its model-facing text remains capped at 2,000 characters with explicit omission counts. Legacy host facts without physical data retain their exact serialized shape, evidence identities and roots. This additive integration does not bump the saved CHPM version or rewrite personality, goals or historical causal threads.

## Bounds and current limits

- At most 12 condition proposals per completed reply.
- At most 512 active conditions across the session. New records are rejected visibly at capacity; existing facts are never evicted to make room. Resolving existing conditions remains possible.
- The recent inspector retains 64 resolved records and 128 operation events. Older closed records/events are removed from this recent view with explicit counters; original narration stays in chat history. This is not an unbounded audit archive.
- Detail is limited to 320 characters; body part/item area to 80; evidence to 600. Context grows with relevant active facts, not the full sequence of previous changes. Existing reconciliation context/deadline guards remain in force.
- Automatic extraction covers available actors and known items from the completed turn's current possession context. It does not simulate off-screen actors, infer room-wide contamination or attach a condition to an item whose canonical ID will only be created by that same reply.
- Private body conditions can guide CHPM decisions. The narrator's public projection intentionally does not reveal a private condition just to remind the reader every turn.

Tests cover literal evidence, independent rejection, treatment versus healing, partial removal, subject scoping, capacity and retention, private projections, saved VN turns and the unchanged request count, failed shared extraction, full-turn replay, manual debug revision guards, real copy/export/import, and the debug form in desktop/mobile browsers. Host integration also covers citable self-inspection, explicit negative facts after resolution, legacy source hashes, privacy during fallback, and twelve live-pipeline turns with mocked inference and zero transcript memory followed by reload, treatment and healing. Model understanding still needs separate live tests.

Clock regressions additionally cover same-room waits, omitted changes, zero-candidate diagnostics, timestamp preservation on rejection, legacy unknown dates, manual edits, replay, reload and copy/export/import. No elapsed time automatically heals, cleans or otherwise removes a physical fact.
