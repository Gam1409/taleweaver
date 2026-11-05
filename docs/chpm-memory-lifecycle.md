# CHPM history, capacity and subjective memory

## Current storage policy: explicit pause, no automatic forgetting

The live pilot still retains up to 512 core events/evidence records and 256 beliefs
per observer. **Consolidation and archival are not implemented.** Raising these
limits without a retention and invalidation policy would only postpone exhaustion.

Before CHPM inference, the host now reserves capacity for a complete worst-case
turn: one scene frame, three perceived excerpts, two interpretations, one own
speech passage and twelve heard passages. That is 19 events/evidence records,
17 host source bindings and two potentially new beliefs. Revisions of existing
beliefs may need less, but admission must also allow new propositions.

At 80% of a resource limit, session settings show a warning. If a whole turn may
not fit, CHPM pauses before its model calls with an actionable message. No old
events are deleted, no identity is reset and no unvalidated narrator silently
takes over. The owner can explicitly select **Standard** and save, or deselect
affected NPCs, to continue with ordinary behavior. Their psychological state is
retained. Re-enabling does not remove the limit. Off-scene or unselected NPCs do
not block a turn. The API exposes counts/status to the owner; private records
remain administrator-only.

This is the specification's explicit degraded-operation option, not a claim to
support indefinitely long live CHPM sessions. A conservative reserve may pause
before the final slot is filled. Existing source invalidation/rewind can reduce
history, but it is not a recommended substitute for consolidation.

## Replay cost

Restore still validates the entire supplied projection against the accepted event
content and original genesis. Pure replay caches up to 64 exact-content frozen
checkpoints in blocks of 32 events. Repeated reads of identical content do not
reapply events; an append can reuse a verified prefix. Scope and identity are part
of the key. A modified projection still fails comparison, including on a cache hit.

The cache is bounded, process-local and disposable. It does not alter persistence,
erase events or skip source binding validation. Parsing/hashing and validating
the source bindings still cost work proportional to the retained history. This
reduces repeated replay work; it does not solve unbounded archival storage.

## Model budget and latency

New settings default to seven logical CHPM requests per turn. Enabling live mode
requires `selected NPCs + 4`: perception, one proposal per NPC, review, and reserve
for one prose repair plus another review. Shadow requires `selected NPCs + 1`.
The ordinary narration request is outside this CHPM-specific limit. Reserved
repair calls are used only on a mismatch; provider retries can add transport cost.

Old settings with smaller budgets still load unchanged. Before CHPM inference,
admission checks the actually present selected NPCs and requests a settings change
if the budget is inadequate. It does not silently raise a saved limit. The settings
UI checks the full selected roster, preventing a surprise when all NPCs are present.

With multiple NPCs, proposals are sequential and text appears only after narration
and review. The UI warns that slow local models may take several minutes. This is
not a fixed ETA. The repair deliberately uses the **Complex narrator role** even
when cognitive proposals use Small, because it rewrites the full response and
must preserve unaffected voices and prose.

## Identity and ordering

The first completed live turn pins original identity. Later character-card edits
do not migrate it, including after off/on. Settings now explain this explicitly.
Experiences can update source-bound beliefs and declared goals without rewriting
that baseline. Long-term personality development or an explicit identity migration
must be separate versioned operations, not an automatic response to a player's
instruction or an inferred temporary emotion.

Production observations now carry a monotonic host `turn_revision` from the
serialized session state, retained on an exact retry. This replaces UUID alphabetical
ordering when timestamps coincide. Timestamp-only legacy observations remain
readable; ambiguous equal-time inputs without a host order fail explicitly.
Simulation minutes still have their separate meaning.

## Planned consolidation: archival truth versus an NPC's memory

The user's proposal of gradually fragmentary memory fits a two-layer design:

1. **Exact archive**: immutable source events and their provenance, available to
   replay, correction and audit. This is not automatically available to the model.
2. **Subjective memory**: bounded recent episodes, compact older recollections,
   retrieval cues and explicit gaps. These are what the NPC can recall in a turn.

An older episode could retain “this person let me down” while no longer exposing
the exact conversation. Its interpretation remains subjective. Missing detail
must not be fabricated, and a summary or repeated recollection must not create
new independent evidence roots. Recalling an old episode is distinct from a new
world event or fresh confirmation that the remembered interpretation was correct.

Age alone must not decide accessibility. Active commitments, repeated experiences,
personal relevance and emotionally significant events may remain accessible longer.
The representation should distinguish detailed, summarized and fragmentary recall,
without pretending those labels are measured human memory strength. RAG relevance
is a retrieval signal, not truth, confidence or psychological importance.

The next implementation should introduce versioned episode records containing:
observer/session scope, time interval, source IDs and root IDs, participants,
summary, retrieval cues, unresolved contradictions and explicit unknown details.
Bounded recent events can then move to an archive-backed checkpoint only after
equivalence checks for beliefs, roots, identity, active commitments and replay.

Edited-source invalidation must cover summaries, retrieval indexes and derived
beliefs. Rewind across an archive boundary must remain possible, or the exact
boundary must be made explicit before enabling the policy. Compaction must be
atomic and idempotent; a failed summary model must leave the previous state usable.
None of these archival/consolidation steps is claimed to be implemented here.

Severe experiences can plausibly produce substantial changes in behavior. Their
simulation requires a separate dynamic-state/development layer with provenance
and competing explanations; it must not automatically replace the original
personality or equate one adverse event with a clinical diagnosis. This system
does not establish clinical or psychological validity.
