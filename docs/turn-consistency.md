# Turn consistency and manual recovery

A scene has one saved location for the player and one effective location for each NPC. Names shown in the story are labels; saved movement uses the session's canonical scene IDs.

## Shared travel

An immediate group command, such as “Let us go to the laboratory now”, can move the player. It differs from asking whether someone would like to go, planning a later visit, or sending NPCs ahead while staying behind.

The existing movement confirmation checks the player's actual contribution and an accessible route. If the continuity model proposes only an NPC destination, that destination can supply a candidate for this same check. The NPC movement itself never proves that the player travelled. A proposed shared departure that fails confirmation does not split the party by applying only its accompanying NPC moves. An intentional NPC-only departure remains available.

NPC destinations accept exact IDs, case variants and unique exact labels. Unknown destinations and ambiguous duplicate labels are rejected before changing a character's location. Semantic matching of differently worded places uses the separate [location identity check](dynamic-locations.md), not an exact-name alias guessed by the host.

After preliminary travel and NPC commands have resolved, the narrator receives one current cast, including NPCs already at the destination. Movement reminders describe resolved travel separately. Earlier dialogue cannot bring departed characters back. These are state and prompt safeguards; they cannot prove that a model's prose obeys every fact.

## Repair an existing session

Enable Debug, open **World map**, select a location and choose **Move player here**. The equivalent command is:

```text
/debug move_player "RESEARCH_LAB"
```

Use the actual scene ID shown on the selected card. This explicit correction bypasses travel checks and changes only the current session. It does not move NPCs, advance time, change inventory or run normal arrival scripts. The old staging arrangement is cleared. Normal commands retain the same session lease and recovery boundary.

Each normal NPC movement is saved and displayed once. Its message follows the session language. Reply IDs are explicitly flushed before direction and illustration records are captured, so removing duplicate system messages does not break full-turn regeneration.

## Browser responsiveness

A proxy can deliver many SSE events in one read. The event reader yields to browser tasks at bounded intervals and checks cancellation/session ownership between frames. Completed dialogue and sanitized HTML are cached by weak message/segment identity; streaming a later reply does not repeatedly parse every old reply. Edits and updated identity/portrait context invalidate the relevant cached data.

Punctuation outside a quoted reply stays with that reply. Loose formatting markers do not create empty Narrator cards; meaningful ellipses and standalone question/exclamation marks remain intact. Canonical chat text is preserved.

These changes reduce browser work. They do not accelerate inference or remove the final state checks that keep a turn serialized.

## Item failures and remaining state work

The item response schema distinguishes an existing canonical item from a newly described item. A failed reconciliation records a bounded failure code and, for schema failures, field paths in session diagnostics. Public messages distinguish invalid item data, malformed JSON, timeout, an uncertain inference reservation and an unavailable check. Provider response bodies and credentials are not returned. A failed check preserves the story and valid portrait thoughts/emotions.

Clothing ownership, worn profiles, mutable item properties and bodily conditions
have canonical saved state. The shared post-narration check can record, change,
treat, reduce or explicitly resolve conditions through the
[physical-state ledger](persistent-physical-state.md); it does not infer automatic
healing or guarantee that every literary description was extracted correctly.
Current [item properties](item-state.md) remain attached to existing item IDs.

NPCs can optionally [inspect current accessible state](npc-observable-state.md)
within their configured tool rounds. Reading a fact does not complete an action
or bypass the normal validators. The inference admission queue still coordinates
model requests, rather than retaining a durable queue of player actions.

The [state-reconciliation investigation](research/rp-state-reconciliation-2026-11-07.md)
is a historical experiment report. Its proposed work is not an inventory of
features currently missing from main.
