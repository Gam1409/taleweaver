# Optional CHPM dialogue pilot

CHPM is an opt-in Visual Novel session feature. Existing sessions default to
**Standard** and make no CHPM model requests. No separate inference server or
Concordia installation is required. The pilot uses the configured Small or Complex
role through the existing router and shared admission queue.

## Session controls

Open **Session Memory & Settings → NPC behavior · CHPM pilot**. Select up to three
known characters and save between turns.

- **Standard:** the existing dialogue pipeline.
- **Observe:** compute alternatives and a selected intention without adding them
  to the narrator prompt or suppressing ordinary planners.
- **Enabled:** select dialogue intentions for present selected NPCs, suppress
  their legacy dialogue/social/story-director planning, and review the complete
  narration before publishing it. A semantic review remains fallible.

Enabled mode requires Living World private decisions to be disabled. Rule-based
world movement and established mechanics remain host responsibilities. A single
session should not have two private decision systems controlling the same NPC.

Changing mode or selection clears the pilot's private decision memory, including
the retry baseline. It does not undo world events, inventory, or published story.
The separate declared-agenda ledger survives mode and selection changes.
Changing only request limits preserves current memory. Checkpoint restore restores
the saved mode and memory along with other session state.

## Current scope

This is a bounded dialogue experiment, not the complete CHPM research model.
The pure kernel records provenance, rejects stale/conflicting observations,
validates authored-goal citations, deduplicates candidate kinds, and selects an
intention with a versioned policy. It does not introduce numerical personality,
relationship, attachment, needs, or mood scales, background reflection, new
physical actions, or automatic world progress. Selected dialogue may now explicitly
create or close declared goals and commitments through the ledger below.

The cognitive input contains the selected NPC's authored character/goal/profile,
projected observable excerpts from the player request, and a bounded window of
source-checked witnessed quotations. A separate perception request sees the raw
player message and projects access for each selected present NPC. Individual NPC
cognition receives only the approved excerpts. The host checks observer IDs and
exact quotations; classification of what was publicly observable still depends
on a fallible model. When the player's saved input belongs to a different scene,
incoming NPCs receive no excerpts from it.

This deliberately excludes global history, the player's NPC journal, other NPCs'
private notes and shared RAG. Restricted input can miss conversational context.
Deceptive or instructional text remains untrusted; provenance is not a formal
semantic guarantee against model mistakes.

The older comparison policy `goal-first-v1` ranks supported goal alignment ahead of neutral/unknown,
then conflict. Support/conflict requires a literal authored-goal quote, but the
meaning of the relation is still a model proposal. Unknown is never converted to
zero. Equal-rank alternatives use a stable hash of session, input-message ID and
action kind. Candidate ordering and repeated paraphrases cannot increase a kind's
weight. This is an explicit engineering policy, not a calibrated human model.

Live VN now uses `initiative-gated-v1`. A clarification cannot win merely because
the LLM labels it goal-supporting. It needs a concrete external fact or player's
own intention, with two distinct proposed conditional actions. Equally useful
independent progress wins over that question. Without a valid gate, an independent
intention is selected; the policy fails rather than forcing goal-conflicting
compliance to avoid asking. Acceptance, refusal, negotiation, initiative and chosen
silence remain possible. Reasons and the proposed gate are retained in the trace.
The narrator/reviewer contract rejects generic permission to continue talking or
writing, while preserving relevant decisions that belong to the player. Semantic
classification remains fallible; see [the appraisal guide](chpm-appraisal.md).

## Publication and failure

Enabled replies are buffered. A reviewer checks the selected stance, additional
actions/promises and speech attribution. Successful evidence must quote the
generated text exactly; semantic correctness still depends on the model.
A mismatch permits one complete prose repair using the existing narrator system
prompt and Complex role, followed by another review. An incomplete stream, invalid
review, exhausted budget, or second mismatch fails visibly. No unchecked text is
published and no silent fallback to the standard planner occurs.

The normal recoverable-turn transaction restores failed attempts. Validated text
is released only after the completed-turn recovery boundary is committed.
Database commit and browser display are not a distributed atomic transaction;
after disconnect, the saved chat history is the recovery source.

Observe-mode preparation failure is recorded in its completed-turn status while
the normal narrator continues. Cancellation never becomes a psychological event.

## Persistence and replay

Versioned state is stored in `SessionState.entity_states.__chpm__`; existing full
session snapshots therefore capture it without a database migration. Writes
replace the JSON value and fence the expected revision. Settings changes also use
an SQL compare-and-swap and the existing session mutation lease.

The pilot keeps a high-water decision per selected actor, including the accepted
proposal, source ID/revision/hash, observation time and selected intention. A
duplicate current observation is reusable; an older one is rejected. This bounded
state is **not an unlimited event journal**. Pure replay from a stored observation
and accepted proposal is deterministic; full turn regeneration deliberately asks
the models again. A changed historical reply clears derived pilot decisions
conservatively instead of assuming indirect dependencies remain valid.

The production session writer uses the existing single-worker mutation lease.
CHPM does not add a distributed locking guarantee beyond that host contract.

## Observer memory

The default window keeps 12 quotations per selected NPC (configurable 0–24).
Each entry identifies its observer, speaker, source message, revision, content
hash, scene and kind. The kinds distinguish projected player observations, the
NPC's own speech, and speech heard from another present NPC. Quotations remain
claims or attempted actions, never independent proof that a world event happened.

Before every use, the adapter checks the source session, role, revision, hash,
exact quote and observer. Deleted or edited sources are excluded. Regeneration
removes quotations from that message and invalidates dependent current decisions;
full turn replay and checkpoints restore the saved memory state. Accepted later
utterances with unchanged sources remain their own historical observations.

The live reviewer may extract additional heard speech only for controlled observers
and other physically present speakers. Attribution or audibility uncertainty must
produce omission. Actor IDs and quotes are checked in code; the interpretation of
audibility is still model-assisted. Observe mode retains only projected player
observations because its ordinary narration is not reviewed by CHPM.

Old quotations leave the configured window with an explicit eviction count.
The transcript is separate from the declared-agenda ledger; it is not a long-term
belief graph.
Setting the window to zero stops transcript recall; it does not erase the agenda. The CHPM settings
endpoint exposes memory contents only in the administrator trace; ordinary owners
see counts. Existing explicitly enabled raw session debug and save exports retain
their established access to the complete session state.

## Declared goals and commitments (stage three)

A candidate may optionally propose one `agenda_change`: declare a personal `goal`
or `commitment`, explicitly `withdraw` an active entry, or `report_done`. The
selected change becomes part of the narrator contract. The existing live reviewer
must provide an exact quotation within that NPC's attributed speech expressing
that specific change. A missing, extra, foreign, or non-spoken evidence entry
fails visibly before publication. Goals and promises are never created directly
from a player claim, another character's words, or an unselected candidate.

The host assigns IDs, validates ownership and active target IDs, requires closure
to copy the target's text, and writes the ledger with the completed reply. Each
creation and closure has its own message/revision/hash/quotation provenance.
Semantic agreement, promise attribution, and paraphrased duplicates still depend
on the model reviewer: exact quotations do not prove their interpretation.

The proposal sees only its owner's source-checked active entries, including the
original quotation. This permits returning to unfinished business beyond the
transcript window. It does not require reciting every goal every turn or treating
promises as orders above personality. The deterministic authored-goal ranking is
unchanged; dynamic agenda entries inform the proposed alternatives, not a new
fixed numerical priority. Authored character/goal fields are never rewritten.

`report_done` means **the NPC said it was done**. It closes the dialogue agenda,
not a world quest. It cannot transfer items, award rewards, move an actor, or
prove an action happened. Closing by silence, elapsed time, or an inferred
reaction is unsupported. Reaffirming a promise needs no new entry.

The ledger has at most eight active entries per NPC and 256 total records per
session, including closed entries. Closed records remain in the archive but are
not sent to cognition. Exact repeated active descriptions are rejected; stable
source-bound IDs prevent duplicate application of the same accepted change.
There is no silent eviction or truncation at either cap: a new entry beyond the
cap fails visibly and rolls back the turn. Archive compaction is future work;
Standard mode remains available without discarding the ledger.

Sources are rechecked before cognition independently of `memory_limit`. A missing
or changed creation removes the entry from the usable ledger; an invalid closure
reopens an otherwise valid entry. If reopening exceeds the active cap, preparation
fails visibly instead of hiding obligations. Regeneration retracts matching
creation/closure sources; checkpoints and whole-turn replay restore the historical
ledger. Settings updates preserve the historical retry ledger rather than copying
promises from the completed reply into its own pre-turn snapshot.

Observe mode reads the existing ledger for its proposed decisions but cannot
change it. Standard mode pauses all CHPM processing. Commitments spoken by the
ordinary narrator while CHPM is off or in Observe are not retroactively imported,
and ordinary-mode closures are not automatically reconciled. Existing entries
remain historical declarations, not a guarantee of current world truth. Only
Enabled mode publishes ledger changes after review and transaction commit.

The settings panel shows counts from the last saved state. The administrator trace
includes sources and closure reasons; ordinary owners receive counts only through
this endpoint. The existing explicit raw-debug/export policy is unchanged.

## Requests and cost

Stage two adds up to one shared perception request before individual proposals.
Memory increases proposal input size, bounded by the same per-request limit.
Stage three adds **no logical requests**: agenda evidence uses the existing review.
An active entry adds up to 300 text and 600 quotation characters plus JSON/ID
overhead to its owner's proposal (eight entries: up to 7,200 text characters plus
overhead). The expanded schemas and optional selected change add further input/
output tokens. Real token cost depends on language and tokenizer; the limits below
still apply and fail visibly rather than silently dropping entries.

Defaults are 1,200 output tokens per proposal/review, 24,000 input characters per
request including instructions/schema, and six logical CHPM requests per turn.
The configured role's lower output limit still applies. A repair is separately
capped at 4,096 output tokens and uses the same request-count/input-size limits.
No private decision is requested for absent selected NPCs.

| Mode | Logical requests for N present selected NPCs |
|---|---:|
| Standard | 0 |
| Observe, successful | N + 1 |
| Enabled, first review passes | N + 2 |
| Enabled, one repair and second review | N + 4 |

These counts assume at least one selected NPC is present in the input's scene.
Cross-scene input is withheld without a perception request. For three NPCs, seven
requests are needed to allow a repair; the default six permits the initial review
but cannot cover that repair. The system checks that two requests remain before
starting a repair. Exhaustion is visible, not a silent switch to standard mode.

The normal narrator request is additional. The legacy social request may still
be needed for other NPCs. Router/provider retries or configured fallback may add
physical attempts; the pilot counts logical requests, not transport attempts.

The settings panel reports the last completed turn's calls, repairs, and input/
output **characters**, not token estimates. Existing LLM telemetry uses
`operation=chpm` with perception/proposal/validation/repair phases and records provider usage
when supplied. Character limits are operational bounds, not token guarantees.
Live failures appear in the turn error and normal inference diagnostics; their
rolled-back state is not presented as a successfully completed usage record.

## Inspection and rollout

`GET/PATCH /api/adventures/{session_id}/chpm` are session-owner scoped. Only an
administrator receives the private decision trace; ordinary owners receive
settings, known character choices, and aggregate usage. A stale revision or busy
session rejects changes rather than overwriting a running turn.

Start with Observe and one character. Compare accepted alternatives with a strong
standard baseline, then enable the dialogue pilot in a test session. Measure
unnecessary clarifications, voice consistency, initiative, false review failures,
latency and actual token usage. No live-model quality claim follows from the
mock-based regression suite. Extended psychology, long-term memory consolidation,
all-mode support and a dedicated model configuration are later work.

## Comparative evaluation (stage four)

The explicit [dialogue evaluation tool](chpm-evaluation.md) compares a strong
synthetic baseline and the shared CHPM dialogue pipeline across 41 cases, including RU/EN dialogue, 40-turn authored histories,
six matched personality profiles and seven states of a fully authored adult NPC.
It records actual provider usage where available, failures, repair counts and
final-text latency, and produces a blind human-review pack. It never runs
implicitly during play and does not alter session settings.

Live endpoint testing exposed Markdown-wrapped JSON and display names returned in
ID fields. CHPM now accepts only a complete outer JSON fence, explicitly enumerates
allowed IDs in its model-facing schemas, and rejects duplicate JSON keys. It still
rejects malformed bodies, wrong IDs, quotations absent from the source and
unvalidated replies. A model can still misinterpret a correctly quoted passage;
passing these gates is not proof of semantic fidelity.
No semantic repair or implicit name-to-ID conversion is performed.

Proposal responses now use unique action keys; stored decisions still contain the
original candidate list. Review responses cite exact passage IDs which the host
resolves into quotations before applying existing evidence and agenda checks.
The evaluator records semantic false acceptances with a deliberate narrator
counterexample probe. These protocol changes do not enable CHPM by default.


## Research state core

The independent evidence/identity foundation and its exact matrix coverage are
tracked in [the research roadmap](chpm-research-roadmap.md). The live VN pilot now
uses its pinned authored identity and observer-scoped location/speech records,
committed with the reviewed reply. Off/shadow modes do not advance it; no extra
LLM calls are added. Source edits, rollback, session copy and import preserve or
explicitly invalidate the corresponding causal state. Live proposals now include
bounded source-bound relationship interpretations, alternatives and unknowns;
see [the appraisal guide](chpm-appraisal.md). Calibrated affect/relationship scores
and independent psychological intent selection are still pending. Both supplied research
source files are preserved with checksums. No psychological-accuracy claim follows
from passing the kernel's program-invariant tests.
