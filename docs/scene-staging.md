# Experimental scene pose and placement continuity

Enable **Track scene poses and placement (experimental)** under **Session settings
→ Story & world → Visual novel narration**. Existing sessions default to off.
Normal VN turns share the existing Small / Utility post-narration item/state
request; enabling staging does not add a second staging request. The shared result
is applied before the turn is saved, using the configured role deadline and the
existing inference admission queue.

A standalone fallback exists when no shared result was prepared. It uses the
same evidence and completeness rules; a failed or incomplete shared request does
not trigger another staging request. See [shared scene continuity](scene-continuity.md).

The extractor receives the present public cast, previously established staging,
and the completed narrator text. It proposes only scene-local posture and relative
placement changes, with exact source quotations. Unknown actors, missing quotations,
invalid character targets and invented object anchors are rejected. Intentions,
claims, hypothetical events and earlier moments are excluded by the extraction
contract; quotation checks do not prove semantic correctness. Model accuracy still
needs evaluation on actual stories.

Supported postures are standing, sitting, lying, kneeling, crouching and on all fours. A placement
relates a character to another present character or an explicitly mentioned scene
object. No precise distances, limb coordinates, private feelings or new objects
are inferred. Missing deltas retain established facts. Explicit uncertainty clears
them. Changes to scene, canonical position, presence or a referenced character's
placement invalidate dependent facts. Re-enabling the setting starts fresh.

Poses live in `entity_states.__scene_staging__`; placed props use the existing
`__scene_props__` registry. Both remain separate from mechanical
permissions. The analyzer cannot change scenes, presence, inventory, ownership or
clothing. Clothing continues to come from the existing equipment/wardrobe pipeline;
staging does not turn unapproved clothing changes in prose into events. Grounded
clothing changes use [narrated-item reconciliation](narrated-item-reconciliation.md).

The next narrator receives a compact data projection with an explicit instruction
not to repeat it. A completed illustration snapshot receives pose and placement
explicitly for both the player and NPCs. Historical snapshots are not updated by
later turns. Their provenance quotes are kept out of public visual facts.

An incomplete reply, oversized input, rejected delta or model failure marks staging
**unconfirmed** and discards stale pose assumptions. When the current cast is known,
a missing or failed extraction preserves still-valid command-owned poses and
placements with their original sources, including those of other actors and
earlier turns. These retained facts remain available without a new pose command.
Changed presence, scene, origin or unavailable targets invalidate them; a later
supported update or explicit clear can replace them. An actor-specific rejected
delta retains its existing uncertainty behavior. An early abort without prepared
cast information keeps the conservative current-command fallback.

A model failure does not discard the narrator's reply. Illustrations use the
available validated facts and explicit narration, plus canonical appearance and
clothing; unconfirmed staging retains its warning. Database failures and
turn cancellation still use the existing turn recovery path. This is continuity
assistance, not a guarantee that an image model will follow the resulting composition.
