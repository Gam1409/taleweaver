# CHPM history, capacity and subjective memory

## Current storage: exact archive and bounded working history

Current core Snapshot schema 4 keeps at most 256 active events. When that window fills, the
oldest 128 events move atomically to an immutable archive block in the same saved
Mind. Events, source bindings, evidence roots, beliefs and pinned identity are
retained exactly. The total cap is 8,192 events/evidence records/source bindings
and 2,048 beliefs per NPC; 32 psychological identities per session remain the cap.
This is **lossless journal archival, not byte compression or unlimited storage**.
The full evidence/source projection is still saved and validated.

Earlier core snapshots migrate through the current reader while preserving their
events and source identities; the host envelope is independently versioned at 6.
Restore replays archive plus active journal; duplicate archived
IDs, changed sources, corrupt projections and wrong identities still fail.
Rewind, source retraction and session copying cross archive boundaries. Archival
commits with the reviewed turn; failed turns never publish a partial rollover.

Before inference, `chpm/capacity.py` reserves **81 events/evidence records,
75 source bindings, three potentially new beliefs and two affect/need dimensions**
per active observer. These bounds include frame/difference sources, perceived
excerpts, tool evidence, causal annotations, up to four stable state observations
and four recovery fragments. At 80% of any total limit, settings warn. If a complete
turn may not fit, admission raises a recoverable analysis failure before dispatch.
Keep playing may use explicitly indicated simplified RP; Strict stops. Neither
policy deletes psychological history. Choosing Standard or deselecting NPCs preserves
their saved history. Re-enabling does not reset the finite limit.

## Fragmentary recall without fabricated summaries

Live appraisal sees six recent speech/world-change sources (up to 1,000 characters
each). Older sources form chronological groups of 16; these are deterministic
retrieval groups, **not model-inferred semantic episodes**. Perceived speech and
confirmed world differences cue lexical retrieval of at most three older source
fragments, each at most 300 characters. Unobserved player narration cannot cue
retrieval. Common words are filtered; matching and recency determine selection.
This default lexical path has no embeddings, sentiment scoring, clinical
memory-strength estimate or extra LLM summary call. Synonyms without lexical
overlap can miss. Opt-in [semantic NPC memory](chpm-semantic-memory.md) augments
retrieval from the same observer-owned evidence; it does not index notebooks.

Each fragment carries the original source alias and a scoped group fingerprint.
The original record/root IDs remain authoritative. Retrieval never adds events,
independent confirmation, belief strength or assumed details. Citations may use
only the exposed contiguous fragment. Historical observations cannot overwrite
current host facts. Missing recall is not evidence that an event never happened.
Counts report older sources, groups, matches, returned fragments and omitted
matches. Derived groups are rebuilt from accepted sources, so edits/rewind cannot
leave a stale persistent summary or retrieval index.

The separate short dialogue window and its `memory_limit` setting are unchanged;
zero disables that window, not the enabled core's private appraisal history.
Active promises/goals remain in the separate agenda. The eight-recent-belief view
is unchanged: there is no semantic retrieval of old beliefs yet. Emotionally
weighted salience, associative retrieval, learned episode summaries and selective
loss of detail in storage remain future policies. This version reduces what the
model sees while retaining the exact audit record.

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

New settings default to eight logical CHPM requests per turn. Enabling live mode
requires `active NPCs × (1 + agent_steps) + 5`: perception, one proposal per NPC,
configured optional tool rounds, review, and reserve
for one shared proposal retry plus one prose repair and another review. Shadow requires `selected NPCs + 1`.
The ordinary narration request is outside this CHPM-specific limit. Reserved
repair calls are used only on a mismatch; provider retries can add transport cost.

Old settings with smaller budgets still load unchanged. Before CHPM inference,
admission checks the actually present selected NPCs and requests a settings change
if the budget is inadequate. It does not silently raise a saved limit. The settings
UI checks the configured active limit; the selected roster can contain 20 NPCs.
See [cast scheduling](chpm-large-casts.md) for direct-participant overflow and costs.

With multiple NPCs, proposals are sequential by default; the optional concurrency
setting allows up to four independent analyses within the connection policy.
Text appears only after narration and review. Slow local models may take minutes. This is
not a fixed ETA. The repair deliberately uses the **Complex narrator role** even
when cognitive proposals use Small, because it rewrites the full response and
must preserve unaffected voices and prose.

## Identity and ordering

The first completed live turn pins original identity. Later character-card edits
do not migrate it, including after off/on. Settings now explain this explicitly.
Experiences can update source-bound beliefs and declared goals without rewriting
that baseline. The [developmental reflection policy](chpm-development.md) now adds tentative
source-bound qualifications. An explicit identity migration remains separate, not an automatic response to a player's
instruction or an inferred temporary emotion.

Production observations now carry a monotonic host `turn_revision` from the
serialized session state, retained on an exact retry. This replaces UUID alphabetical
ordering when timestamps coincide. Timestamp-only legacy observations remain
readable; ambiguous equal-time inputs without a host order fail explicitly.
Simulation minutes still have their separate meaning.

## Next policies and psychological limits

Archival and lexical fragments provide the provenance foundation, not a complete
simulation of human forgetting. A future semantic consolidation policy must
preserve source/root links, contradictions, uncertainty, active commitments and
retractability. Its failure must leave the previous state usable. A summary or
repeated recollection must never count as independent evidence.

Severe experiences may plausibly change behavior. Current source-bound affect and
slow developmental reflections use their own qualitative policies; calibrated
emotion dynamics and enduring identity migration remain separate work. They must not
replace the original identity or turn a single adverse event into a clinical
diagnosis. This system does not establish clinical or psychological validity.
