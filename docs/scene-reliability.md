# Scene reliability and recovery

Narration rewrites now keep append-only revisions in `chat_messages.versions`.
The Versions button previews revisions and restores the latest response's text.
Restore creates another revision; it never replays actions, inventory changes or
rewards. Both replacement and evidence invalidation commit together. Copy/export
preserves revision history. Derived poses and prop placements carry message and
revision IDs and are retracted when their source is replaced. Old illustration
jobs remain fenced by snapshot nonce and hash.

Experimental scene staging also extracts evidence-backed prop placements. A
removed item remains owned; removal alone never implies a floor placement. Only
confirmed, quoted positions enter illustrations. Provisional records are retained
but omitted from rendering. Ownership/equipment is checked again when projecting
props. Session checkpoints carry these records with the rest of entity state.
Turning staging off clears derived staging and props.

Image preparation checks literal character names, declared cast count, visible
managed-clothing names and confirmed prop positions. A missing anchor triggers
one feedback retry, then a visible failure before image submission. The checks
prove token coverage, not semantic correctness or image accuracy. Arbitrary
extra characters or contradictory prose cannot be ruled out by substring checks.
For tracked scenes, the existing bounded frame extractor supplies ephemeral
pose/expression/lighting context. A second extraction checks supported saved
postures and character-relative placements. This model check can also be wrong;
its diffs are recorded in opt-in visual traces. Scene-object relational semantics
remain less well covered than actor-to-actor relations. No NSFW prompt is changed.

Background movement near the player waits while narration is recent (60 seconds,
or up to 300 seconds with an open scene focus). A bare active sequence does not
freeze the world indefinitely. Deferred moves revalidate world rules in a later
window; three deferrals cancel the attempt with a public generic explanation.
Foreground narrator-driven movement is unaffected.

Checkpoint retention keeps five unpinned automatic checkpoints; manual and pinned
checkpoints are protected. The timeline offers a Keep checkpoint button. New
checkpoints restore active sequence and session status. Account achievements stay
earned; the confirmation dialog explains this and legacy snapshot limitations.

Overflow GM notes move to an archive key rather than being discarded. Active
note and prompt budgets are unchanged; explicit forget/clear still removes notes.

Post-turn hook effects and completion ledger entries commit together. Internal
combat commits are suppressed only within a hook. A rolled-back timeout or
connection error gets at most one retry; other failures remain recorded. The
standard session mutation lease serializes these operations (single worker).
The diagnostics panel lists recent hook outcomes and metadata-only recall
counters: candidates, positive-score results, selected items, duplicate skips,
budget skips, zero-hit projections and lexical-only projections. Recall counters
are per audience projection, process-local, and reset on restart; hook history is
stored in the database. Embeddings are not silently enabled.

Upgrade the database with the normal Alembic migration before starting the new
backend (`c7e9a1b3d524`). The migration adds narration history columns and hook_runs.
