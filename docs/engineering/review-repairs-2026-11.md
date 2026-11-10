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

The original review also covers independent scene-delta validation,
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

## Wave 5: bounded wire correction and finite-key grammars

- Normalize only the demonstrated singular choice-ID alias, using the current
  observer's exact motive catalogue. Conflicts and unknown IDs remain errors;
  normal schema, evidence and semantic validation still run before publication.
- Report local format corrections separately from model requests and retries.
- Expand finite dictionary keys only in the transport schema for grammar backends
  that ignore `propertyNames`. Keep the equivalent compact prompt representation
  and verify that the dense decision fixture still fits its original budget.
- Live baseline measurements found both a truncated 1,200-token proposal and an
  independently malformed proposal/retry. These offline repairs do not establish
  that the complete live NPC pipeline now succeeds; that needs another live run.

## Wave 6: observer-scoped scene continuity in NPC cognition

- Reuse the existing staging and scene ledgers for current poses, visible placed
  items and process changes. Share the loaded scene scope and the same projection
  between normal cognition and simplified narration; send no extra model request.
- Keep concealed or unspecified prop visibility private to its owner. Public
  placements still require a current item owner, presence and confirmed location.
  Renaming or transferring a canonical item invalidates stale labels or ownership;
  a corrupt pose affects only its actor's projection.
- Preserve legacy source hashes by omitting unknown additive fields. Bound the
  observer projection with explicit omission counts while retaining its ledger.
- Record witnessed process changes through the existing world-event mechanism.
  Missing visibility is unavailable, not an inferred ending; changing rooms does
  not establish that a process in the previous room stopped.

## Wave 7: state-only background snapshots

- The existing snapshot endpoint can omit transcript loading and serialization.
  Periodic and explicit state refreshes use that option, retaining the displayed
  transcript. Initial loads, stream recovery, agent reload and undo still request
  complete history.
- Mark partial responses explicitly and reject one when a full load was requested.
  Keep session authorization, busy-session read-only behavior, request ownership,
  cancellation and the full-body deadline intact. No history cursor or parallel
  history store is introduced for data the background consumer never used.

## Wave 8: independent reconciliation after item failures

- Validate shared item proposals independently with the existing strict item
  contract. Keep original action indices for deterministic new-item IDs and prop
  references; an invalid entry cannot discard a separate valid item action.
- A localized canonical item denial records its touched subjects. The existing
  extraction request may retain source-backed state for unrelated known targets.
  Related subjects and room-level proxies remain unconfirmed. General rules
  denials do not gain this exception.
- Preserve the established independence of valid physical-state candidates when
  an ordinary item candidate fails. Independent deltas still use the original
  ledger source, ownership, visibility, operation and clock checks.
- Rejected state updates are counted and reported; no second extraction request
  or successful replacement for the denied inventory action is introduced.

## Wave 9: outfit producer identity contracts

- Reuse the existing recovery schema pattern to bind outfit drafts to the current
  character's known garment IDs, with null for new items. Keep the server as the
  owner of new identities and retain normal already-worn filtering.
- Clarify the same identity distinction in the shared authoring item description
  and the producer prompt. Independent actors receive independent schema objects;
  no shared base schema or saved wardrobe is mutated.

## Wave 10: recover registered garment placement from evidence

- Repair the existing debug recovery context's missing session identity so scoped
  possession checks can include the NPC's registered garments. Preserve that
  ownership check rather than treating unavailable IDs as new acquisitions.
- Apply reviewed placement evidence to an already-worn garment without creating
  another item. Restoring normal coverage requires an explicit flag and an exact
  restoring quotation; omitted placement never resets exposed regions.
- Preserve original acquisition provenance when correcting placement. Bind preview
  fingerprints to base visual profiles and message revisions as well as text,
  so an intervening appearance or history update requires a fresh preview.
- Reuse the recovery history loader with an optional saved-message cutoff,
  stable timestamp/ID ordering, whole-message limits and an explicit limited flag.
  The illustration pipeline does not yet consume this optional history window.
- Keep preview/apply review, age/detail policy and garment coverage validation.
  Tests cover the full debug path, not just the isolated evaluator.
- Update the older item-denial integration test to verify the intentional Wave 8
  behavior: retain the item refusal while exactly one shared extraction checks
  unrelated state. General rules denials still skip the shared request.

## Wave 11: failure-path review follow-ups

- Treat an undo HTTP 5xx as an unknown mutation outcome. Preserve the displayed
  world, lock input and require authoritative session recovery. An explicit 4xx
  refusal still leaves the previous usable state available.
- Retain fixed metadata labels for wardrobe preview/schema/evidence retries,
  item repair, NPC lookup/narration repair, simplified continuation and Living
  World decisions. Arbitrary strings, story content and credentials remain
  excluded from the system diagnostic metadata.
- Recheck producer contracts and source ownership separately from the lifecycle
  review: cancellation, stale responses, regeneration, undo, session transfers,
  item/pose provenance and import/copy paths. Semantic extraction accuracy still
  requires a future live test; offline coverage is not a model-quality claim.

## Wave 12: distinguish provider status from local identifiers

- Reproduce false quota/service diagnoses when a local ValueError contains 429,
  502, 503 or 504 inside a source identifier. These numbers alone are not proof
  of a provider response status and previously hid the local failure's traceback.
- Reuse the central diagnostics owner for HTTP status matching. Prefer typed
  exception/response status metadata; accept explicit legacy HTTP/status text.
  Preserve recognized provider phrases and the existing safe public messages.
- Unrelated local failures now reach the existing unexpected-error log path,
  without exposing source identifiers in the client response. Full gameplay and
  public-error regression coverage passes alongside genuine 429/503 cases.
- Live testing found both successful validated NPC turns and a separate proposal
  semantics rejection. The classifier repair does not claim to resolve that model
  decision error or every failure previously presented as a quota problem.
- Correct the error-privacy integration checks to inspect visible SSE content and
  error details. Random receipt UUIDs can contain 429/503 without leaking a status.
  Deterministic receipt IDs reproduce both old false failures; all 120 affected
  gameplay and public-error checks pass after this test-only correction.

## Wave 13: unavailable NPC references remain unavailable

- Eliminate empty ID enums before composing a prompt or transmitting its schema.
  With no known beliefs, revision arrays are forced empty instead of creating an
  invalid grammar rule. Nullable references still permit only null; known IDs
  remain usable when they become available on a later turn.
- Propagate unavailable required references through shared definitions, unions,
  arrays and observer maps. Reject an impossible required root before generation.
  Do not widen an allowlist or replace a missing reference with an invented ID.
- Preserve canonical NPC state, source validation and the existing request budget.
  This is a wire-contract repair; no psychological update or paid retry is added.

## Wave 14: shared structured-output policy

- Route NPC technical calls and ordinary structured tasks through the same output
  selector. Preserve explicit compatible-endpoint modes, existing sampling,
  inference admission and bounded retry behavior. Keep freeform narration freeform.
- Project conditional operation schemas into complete alternatives for decoder
  compatibility. Retain canonical models, evidence checks and deferred constraints
  in local validation; ground deferred rules in the prompt as well.
- Use native schema transport where the contract fits. Select JSON-only or
  prompt-only compatibility paths before generation for unsupported contracts.
  Do not mislabel Anthropic's schema-less JSON request as native enforcement.
- Reuse one structured connection probe for all providers and keep temporary role
  settings temporary. Display compatibility notices only in LLM settings.
- Add content-free output-contract diagnostics and tests of the installed provider
  adapters with real sockets forbidden. Review also covers unavailable references
  inside fixed tuples and original text rules after structural projection.
- Preserve technical JSON before narration cleanup: voice tags, literal thinking
  tags, fence markers and comma/bracket text inside strings are data. A valid
  document is not repaired. Ordinary narration retains its voice normalization.
- Treat an impossible source-bound NPC contract as recoverable before reserving
  a model call, retaining the existing continuation and request-budget policy.
- See [technical structured output](../structured-output.md) for the supported
  boundaries. Live model correctness is a separate validation step.

## Wave 15: causal records coexist with psychological interpretations

- A live two-NPC turn reached accepted narration but failed at commit: the causal
  graph treated an interpretation's evidence ID as an observation source ID.
  Interpretations deliberately have no direct host source binding.
- Read observation records from the existing validated chronological event ledger,
  including archived events. Keep interpretations and their beliefs intact; never
  invent source bindings or discard psychological history to avoid the failure.
- Regression tests reproduce the original KeyError before opening or updating a
  causal thread. Existing graph tests cover archival, serialization, reordering,
  source retraction and session forks.
- Replaying the captured live outputs through the repaired completion path saves
  both NPC decisions and the causal thread without new model requests. This replay
  verifies the commit boundary; it is not a new successful live gameplay turn.
- See the [live validation report](structured-output-live-review-2026-11-10.md)
  for model correctness failures that remain outside this focused host repair.

## Open illustration consistency decision

- F13 remains open: a source-backed visual exposure atom can conflict with the
  frozen wardrobe after a failed clothing action. Current rendering does not
  resolve that conflict by consulting historical wardrobe evidence.
- The owner requested checking history, including earlier adult RP context.
  Genre is not garment evidence. Review only messages up to the selected moment;
  current clothing must not replace historical clothing in an older illustration.
- The existing recovery preview can now correct missed registered-item placement,
  but it changes current state only after review. Automatic historical image
  repair and its confirmation policy have not been implemented.
