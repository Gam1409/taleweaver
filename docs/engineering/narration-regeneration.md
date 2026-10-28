# Regenerating the latest narration

The response button rewrites the latest completed assistant message in place. It
does not replay the player's action, reroll checks, advance time or restore an
earlier world state. The original response remains intact on model failure.

The narration role's configured deadline controls the request. OpenAI-compatible
providers use the same shared provider deadline as normal narration. The browser
does not impose a second fixed timeout. Normal API requests keep their default
15-second timeout; explicit cancellation remains supported.

Regeneration holds the existing session mutation lease and registers foreground
activity with the memory scheduler. It releases its read transaction before the
model call. Replacement is a conditional write checking both the original content
and the latest conversation message, followed by one atomic commit of derived
state updates. An intervening change returns a conflict without overwriting it.

The rewrite receives the saved VN pace, optional narration additions, formatting,
voice-tag catalog, world frame, current scene/time and NPC presence. Instructions
preserve the original beat rather than starting a new one. As with normal model
output, semantic fidelity still requires live testing with the selected model.

After an actual text change:

- Related NPC journal entries are removed and the existing extraction task is
  requeued; NPC identities, portraits and game outcomes remain intact.
- Related grouped summaries are invalidated. The memory index epoch changes so
  old jobs cannot commit stale results, and memory maintenance is requested.
- An existing illustration snapshot retains its original visible facts but gets
  the new text/hash and a new job nonce. Its old image association is invalidated.
  The UI reloads illustration status when the response text changes. Missing
  historical snapshots are not reconstructed from potentially newer appearance.

The playtime heartbeat uses one authorized atomic SQL update. It counts visible
session time separately from the story clock and discards long offline gaps.
The merge migration joins the memory-fragment and playtime schema branches; both
parent upgrade paths are covered by isolated database tests.

Validation covers authorization, stale requests, failure preservation, configured
deadlines, derived memory, illustrations, saved VN settings and both migration
paths. Frontend tests are available through `npm run test:regeneration`.
