# Session integrity review repairs

The review baseline is `0eb76d04`. Changes are delivered in separately verified
waves. Model responses in regression tests are mocked. Separate live benchmarks
use synthetic data and keep their private endpoints and artifacts out of Git.
Passing regression tests establishes host contracts, not model reasoning quality.

## Wave 1: narration and foreground ownership

- Reject known incomplete regeneration before replacing the saved response.
- Extend the existing writer lease through the entire Play-Agent cycle and its
  settings updates. Explicit capability delegation allows the nested narration
  turn to use that same lease, without granting background tasks implicit access.
- Bind agent and terminal epilogue responses to their originating session,
  request controller and snapshot revision. Navigation aborts those requests.
  Final agent history reload keeps input locked until it finishes.
- Reuse the frontend lifecycle harness across chat and ownership regressions.

The original review's remaining work covers independent scene-delta validation,
clothing/provenance contracts, NPC host facts, source retraction, history polling,
causal projections, diagnostics and structured technical model requests.

## Wave 2a: independent staging validation and operation schemas

- Reuse the existing staging owner for bounded, per-entry validation. Malformed
  props/explicit atoms do not invalidate independently valid poses.
- An invalid or unverifiable pose removes only its identified actor's pose and
  stale character-relative placements. Unrelated actors retain confirmed facts.
  This does not authorize movement, teleportation, ownership or clothing edits.
- Solo undressing uses one participant, consistently with other solo acts.
- The scene update JSON schema now exposes the host's operation-specific required
  fields, including the stable key for a new record. Existing saved data retains
  the same schema version and shape.
- Diagnostics distinguish partial rejections from a fully unconfirmed frame and
  include schema-invalid pose proposals in both proposal/rejection totals.

## Wave 3a: NPC request boundaries and technical diagnostics

- Reuse the existing recoverable-analysis failure path when an accepted chat input
  exceeds NPC perception's 6,000-character or 32-fragment limits. Continue mode
  keeps the full player request for narration and preserves confirmed identity;
  strict mode still stops. Invalid source ownership remains a hard failure.
- Reuse the custom endpoint's saved structured-output selection for technical
  CHPM calls. Prompt, JSON object and JSON schema modes are checked at the actual
  mocked HTTP boundary, including dynamic allowed IDs. Narration stays freeform.
- Allowlist content-free operation/phase metadata for shared state reconciliation,
  staging, simplified RP and narration regeneration.
- Filter causal pointers against the final bounded audience projection. Omitted,
  stale and needs-confirmation causes cannot remain confirmed causal links.

## Wave 3b: independent source lifecycle

- Source retraction and partial history copies unconfirm only the actors whose
  pose sources are missing. Other source-backed poses retain their own bindings.
- Replacing a narration removes its message-local acts from the frozen visual
  snapshot, while keeping already committed clothing appearance intact.

## Owner clarification: debug deletion is turn undo

Deleting story text must also undo the turn's consequences. Use the existing
latest-turn snapshot for the last completed turn; use Chronicles checkpoints for
older history. Refuse deletion when no safe snapshot exists. Do not introduce an
additional 20-turn snapshot archive. A text-only deletion that keeps consequences
is not the selected behavior.

## Wave 4: debug undo through the existing snapshot owner

- Replace arbitrary message deletion with atomic rollback of the latest complete
  turn. Ownership, debug access and the session writer lease remain mandatory.
- Reuse full-turn snapshot restoration for character identity and goals, clothing,
  item ownership, poses, locations, health, journals and the game clock. Preserve
  current debug visibility, stop the Play-Agent and invalidate late memory jobs.
- Refuse older or unavailable snapshots with the Chronicles checkpoint path.
  Invalid snapshots roll back the whole transaction, including prior SQL deletes.
- Confirm the destructive action and reload the authoritative session before
  unlocking input. Navigation fences old responses; an unconfirmed network
  outcome requires session recovery before another action.
