# Experimental scene pose and placement continuity

Enable **Track scene poses and placement (experimental)** under the session's
**Visual novel narration** settings. Existing sessions default to off. This adds
one Small / Utility structured request after a completed narrator response and
before the turn is saved. It uses that role's configured timeout and the existing
inference admission queue. It does not start concurrent model requests.

The extractor receives the present public cast, previously established staging,
and the completed narrator text. It proposes only scene-local posture and relative
placement changes, with exact source quotations. Unknown actors, missing quotations,
invalid character targets and invented object anchors are rejected. Intentions,
claims, hypothetical events and earlier moments are excluded by the extraction
contract; quotation checks do not prove semantic correctness. Model accuracy still
needs evaluation on actual stories.

Supported postures are standing, sitting, lying, kneeling and crouching. A placement
relates a character to another present character or an explicitly mentioned scene
object. No precise distances, limb coordinates, private feelings or new objects
are inferred. Missing deltas retain established facts. Explicit uncertainty clears
them. Changes to scene, canonical position, presence or a referenced character's
placement invalidate dependent facts. Re-enabling the setting starts fresh.

The state lives in `entity_states.__scene_staging__`, separate from mechanical
permissions. The analyzer cannot change scenes, presence, inventory, ownership or
clothing. Clothing continues to come from the existing equipment/wardrobe pipeline;
this first version does not turn unapproved clothing changes in prose into events.

The next narrator receives a compact data projection with an explicit instruction
not to repeat it. A completed illustration snapshot receives pose and placement
explicitly for both the player and NPCs. Historical snapshots are not updated by
later turns. Their provenance quotes are kept out of public visual facts.

An incomplete reply, oversized input, rejected delta or model failure marks staging
**unconfirmed** and discards stale pose assumptions. A model failure does not discard
the narrator's reply. Illustrations display a warning and fall back to explicit
facts in that reply, plus canonical appearance and clothing. Database failures and
turn cancellation still use the existing turn recovery path. This is continuity
assistance, not a guarantee that an image model will follow the resulting composition.
