# Interrupted answers and retry

A local or remote model can time out after it has begun writing. The inference
queue may then block further requests because the remote computation could still
be running. A failed NPC journal task is a separate background operation; it cannot
delete the narration.

The normal turn now marks its recovery record complete in the same transaction as
the assistant message and gameplay state. A later map, checkpoint, background
scheduler or transport failure cannot rewind that committed response. Error events
can carry the committed assistant ID, allowing the browser to reload that answer
instead of offering a duplicate action.

If a connection is interrupted before commit, normal recovery still rolls back
uncommitted gameplay changes. Visible narration already received by the player is
retained separately as an **unfinished draft**. A successfully validated buffered
NPC Personality reply can also be retained; rejected/private buffered candidates
are never exposed as drafts. Drafts do not enter canonical chat history, memory,
NPC knowledge, inventories or other world state. This cleanup runs on handled
cancellation/errors; an abrupt process kill before cleanup cannot preserve RAM-only
text. Drafts are capped at 200,000 characters and explicitly marked when truncated.

Reloading the session exposes a pending original action and its draft through the
owned chat snapshot. The Retry button resends the original action; the backend
reuses its durable user message. Cancel dismisses the banner for the current visit.
Successful commit clears the draft. Polls during an active turn do not advertise a
second retry. Full turn regeneration preserves its existing rollback-to-original
semantics; an unsuccessful replay never becomes a fresh-action retry.

Inference admission rejections now defer NPC journal work with a delay, preserving
its retry budget and original narration. Manual retry clears the journal backoff.
Provider failures still have their existing bounded failure policy.

An uncertain inference reservation still requires the administrator to verify that
the remote request has ended, then clear it in the [Inference queue](inference-queue.md).
Clearing the local reservation does not stop remote generation or rerun gameplay.
