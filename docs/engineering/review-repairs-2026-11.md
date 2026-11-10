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

## Wave 16: partial clothing, atomic item chains and source passages

- Reuse the existing worn-coverage representation in post-narration item actions.
  Explicit partial placement stays worn; omission preserves known placement and
  an explicit empty array restores coverage. Wire and host validation agree on
  worn-only placement, unique regions and existing clothing policy checks.
- Replace the unconditional duplicate-item rejection with bounded atomic chains
  for one existing ID. Require completed, source-ordered, non-overlapping evidence
  and continuous ownership. A failed terminal action or schema-invalid peer cannot
  leave its earlier removal applied. Preserve unrelated items and source indices.
- Reuse the NPC review's passage segmentation through a shared pure text helper.
  Item and condition evidence can reference an unchanged current-message passage;
  unknown IDs and paraphrases retain their normal validation failure. No extra
  inference request, fuzzy quote repair or additional state store is introduced.
- Local four-turn gameplay tests cover an adult garment's partial placement,
  removal and transfer, another transfer and basket placement, washing, drying
  and partial dressing. The tear survives cleaning. Run with staging on and off;
  verify actual saved ownership, worn coverage and assistant-message provenance.
- Additional tests cover independent-item failure, mechanics idempotence, legacy
  literal evidence, source fidelity in literary text and debug recovery boundaries.
  These deterministic tests do not establish live-model extraction quality.
- The earlier 18/23 live result remains the baseline until another live run.
  In particular, ambiguous metaphors need semantic evaluation with a real model.
- Validation: the complete backend run passed 5,075 cases and exposed one outdated
  staging mock expecting the old narration string. Update it to assert the exact
  two source passages, retaining the message/pose assertions. The subsequent 81
  boundary checks and 490 affected-feature checks pass. Ruff is clean and mypy
  accepts all 908 backend source files. Live generation remains paused by request.

## Wave 17: bind exact source occurrences

- Extend the existing shared passage index with exact character offsets while
  preserving its numbering, text values and existing callers. No semantic/fuzzy
  quote lookup or parallel memory store is introduced.
- Bind extraction evidence to request-scoped narration/room references, then
  assign source kind and offsets locally before existing domain validation.
  A current narration fact cannot be lost merely because the model labels its
  source as authored room text. Room text still establishes environment only.
- Reuse the router's existing schema projection for a per-request finite schema
  in native, JSON and prompt modes. Keep canonical saved models and legacy source
  shapes compatible. No additional extraction or repair request is sent.
- Preserve exact occurrences across scene facts, poses, props, conditions and
  item checks. Save assistant-message provenance after flush. Copy/import remaps
  IDs without looking up replacement words; missing sources stay unavailable.
- Use verified spans when ordering item chains whose source words recur later.
  Literal-only ambiguous chains still fail; ownership continuity, narrative
  ordering and atomic rollback are unchanged.
- Verify repeated quotes in four later turns, distinct occurrences in one
  message, cross-turn stale references, authored/current source collisions,
  wrong offsets, legacy serialization and independent rejection. Real provider
  adapters are exercised with HTTP intercepted, not live paid requests. Offline
  KoboldCpp conversion covers populated, tiny and empty source catalogues.
- This wave establishes source identity. It does not establish that a model
  extracts every fact or correctly distinguishes every recollection from an event.
- Validation: the complete backend suite passed 5,129 tests. The final affected
  suite passed 678 tests, including the last two literal-ambiguity regressions.
  Ruff check/format is clean and mypy accepts all 911 backend files. Fifteen
  offline KoboldCpp grammar conversions passed; 1,500 differential text cases
  preserved the published passage index and exact offsets. No new live model
  request was sent in this wave.

## Wave 18: local proposal failure and natural continuation

- Give completed invalid/truncated proposals their own recoverable error type.
  In live Keep playing mode, reuse the inactive-character boundary for a rejected
  NPC while preserving independently usable peer decisions. Strict, transport,
  cancellation, shared-analysis and host-integrity failures keep their existing
  whole-turn boundaries. With no surviving decision, use normal recovery.
- Remove the failed actor's complete turn-local drafts, including observations,
  recalled agendas, causal projections and temporary gap cursors. Preserve that
  actor's original saved state. Shared narration review still gates publication;
  a conflict can require repair or abandon all proposed psychological changes.
- Keep the single shared retry and restore its serial budget accounting after a
  deferred actor. Add bounded per-actor diagnostics and a partial status outside
  the narration. Existing checkpoints, import/copy and saved-state owners remain
  authoritative; the additive diagnostic field needs no schema-version bump.
- Reuse the portrait-presentation owner to exclude new thoughts/emotions for
  locally deferred NPCs while retaining their peers' cues. Check both pre-capture
  and already-captured candidates, independent sessions, and an empty eligible
  cue set without misclassifying it as a source-hash failure.
- Live testing exposed a separate false rejection: INITIATE followed by CONTINUE
  on the same discussion was labelled maintain. The owner approved this natural
  progression. Allow only that additional pair, preserving conditions, grounded
  revision requirements for other transitions and semantic narration review.
- Regression coverage includes both actor orders, sequential/parallel execution,
  schema/semantic rejection, strict rollback, shared review repair/rejection,
  cancellation, hard-error precedence and exact request-budget reservations.
- Validation: a complete backend run passed 5,156 tests before the final narrow
  continuation and portrait-cue repairs. After all repairs, 1,777 affected
  regression tests passed. All 470 frontend tests, Vue type checking and the
  production build passed. Ruff check/format is clean; mypy accepts 912 backend
  files. No further Pod requests were made after the idle/empty-queue check.

## Wave 19: measure omissions against independently defined facts

- Add six reusable kettle-process cases: a literal ending, its negation, an
  ending repeated in recollection and authored prose, a literary ending, a pure
  recollection, and an authored action with no current narrated event.
- Score canonical state, retained identity, current source revision/hash/span,
  and rejected proposals. An empty extraction succeeds only on unchanged-state
  controls; an all-checked marker cannot hide a required change.
- Run those cases through the real shared extractor with staging both enabled
  and disabled. See the [live report](structured-output-live-review-2026-11-10.md)
  for measured results and the distinction between live and captured-response
  verification. These probes do not measure overall RP quality or long-session
  psychological continuity.

## Owner requests addressed by waves 18–19

1. **Localize NPC decision failures.** Investigate the existing per-NPC proposal,
   narration review and commit paths before extending them. One invalid intention
   must not unnecessarily discard another NPC's confirmed updates. Preserve a
   shared world snapshot and compatibility checks for interacting actions; an
   actor leaving cannot simultaneously be treated as still available for contact.
   Do not publish proposals independently when their shared outcome is unresolved.
   Original investigation: `chpm.parallel.prepare` raised the first worker error
   before applying any parallel result; `chpm.continuation.activate` cleared all
   turn-local decisions, minds and agendas. Wave 18 extends those boundaries and
   the shared narration review without creating a second decision pipeline.
2. **Test omissions explicitly.** Add paired cases differing in one world fact,
   literary paraphrases of the same event, and unchanged-state controls. Assert
   expected extracted deltas and persisted state, not a model's own assertion
   that it checked everything. Keep deterministic host tests separate from later
   live extraction-quality measurements. The source-binding wave was followed
   by localized proposal handling and the paired extraction probes above.

## Wave 20: preserve expressive narration and its emotional context

- Trace the existing narrator, history, planner, CHPM review, persistence and comic
  display paths before extending them. Confirmed losses were cue deletion from
  assistant history, repeated-cue clipping in responses and streaming, and removal
  of leading narration tags in the comic parser, including entire cue-only lines.
- Bypass legacy voice normalization/clipping in narrative transport and preserve
  assistant messages verbatim. Protocol reasoning and private presentation footers
  keep their existing boundaries. Explicit context-window budgets remain intact;
  emotion, interjections, pauses and repeated delivery cues are not cleanup targets.
- Keep planner narration cues and accept exact raw scene-focus evidence. Continue
  recognizing the earlier cue-stripped focus representation for compatibility;
  focus still cannot establish world state or authorize transitions.
- Extend the existing narrator context with exact stored experience explanations,
  including archived events, without new inference, state stores or schema changes.
  Add at most two reasons and 512 serialized characters per NPC. Preserve freshness
  and continuity-gap status, observer isolation and the technical decision input.
  Missing appraisals do not establish calm or require emotionally blank prose.
- Keep automatic factual repair and shared-world review. The owner explicitly
  retained that mechanism; expressive delivery itself is not a factual violation.
- Before fixes, new regressions reproduced eleven backend failures and three
  comic-parser failures. After fixes, the 31 focused backend checks and all parser
  checks pass, including exact transport text, failure propagation, stream usage,
  reviewed VN persistence, bounded reasons and stale/archived experience handling.
  A second delivery cue on a tagged dialogue line also stays in the visible text
  instead of disappearing when the first cue occupies the badge.
  Broader validation is recorded below after completion. No live Pod calls were
  made; these checks establish text/context fidelity, not improved literary quality.

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
