# NPC presence

Session entity overrides now retain a `presence` value independently of map
location and discovery: `present`, `audible`, or `absent`. Older saves default to
`present`. This additive JSON field does not require a database migration.

The existing mechanics/continuity model proposes changes via
`updated_entities.presence`. It is instructed to distinguish completed departures
and returns from plans, past events, silence and emotional withdrawal. The latest
completed narrator response can supply a missed event on the following turn.
There is no keyword parser or additional post-narration LLM call. Recognition
still depends on the configured model; an unregistered narrative departure does
not immediately change the UI.

The current-scene entity API and sidebar exclude audible and absent characters.
The Characters directory and stored portraits are preserved. Narration receives
an explicit presence roster: audible characters can speak from outside but cannot
perform physical interactions; absent characters cannot participate. VN social,
possession and wardrobe context exclude non-present characters. Image snapshots
use the filtered scene entities. Real movement to a map location resets local
presence to `present`; existing movement restrictions remain in force.

Entity changes now rebuild narration context even when the clock and player
location did not change. Memory recall retains its existing per-turn cache.
Presence is operational state, not a journal fact or an embedding retrieval result.

Regression coverage includes persistence/reload, departure/return, audible-only
presence, old saves, canonical inventory availability, map movement, and a full
mocked turn checking both the narrator prompt and the streamed UI snapshot.
Live model interpretation and visual browser behavior are not covered by these
automated tests.
