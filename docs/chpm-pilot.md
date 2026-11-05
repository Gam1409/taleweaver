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
Changing only request limits preserves current memory. Checkpoint restore restores
the saved mode and memory along with other session state.

## Current scope

This is a bounded dialogue experiment, not the complete CHPM research model.
The pure kernel records provenance, rejects stale/conflicting observations,
validates authored-goal citations, deduplicates candidate kinds, and selects an
intention with a versioned policy. It does not introduce numerical personality,
relationship, attachment, needs, or mood scales, background reflection, new
physical actions, or automatic promises.

The cognitive input contains the selected NPC's authored character/goal/profile,
the current player request explicitly marked as unverified, and their own last
validated speech where the source still matches. It deliberately excludes global
history, the player's NPC journal, other NPCs' private notes, and shared RAG.
This restricted view can miss conversational context; observer-specific memory
is future work. The player request can itself contain deceptive or instructional
text. Provenance and prompts constrain its interpretation but do not provide a
formal semantic guarantee against model mistakes.

The policy `goal-first-v1` ranks supported goal alignment ahead of neutral/unknown,
then conflict. Support/conflict requires a literal authored-goal quote, but the
meaning of the relation is still a model proposal. Unknown is never converted to
zero. Equal-rank alternatives use a stable hash of session, input-message ID and
action kind. Candidate ordering and repeated paraphrases cannot increase a kind's
weight. This is an explicit engineering policy, not a calibrated human model.

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

## Requests and cost

Defaults are 1,200 output tokens per proposal/review, 24,000 input characters per
request including instructions/schema, and six logical CHPM requests per turn.
The configured role's lower output limit still applies. A repair is separately
capped at 4,096 output tokens and uses the same request-count/input-size limits.
No private decision is requested for absent selected NPCs.

| Mode | Logical requests for N present selected NPCs |
|---|---:|
| Standard | 0 |
| Observe, successful | N |
| Enabled, first review passes | N + 1 |
| Enabled, one repair and second review | N + 3 |

The normal narrator request is additional. The legacy social request may still
be needed for other NPCs. Router/provider retries or configured fallback may add
physical attempts; the pilot counts logical requests, not transport attempts.

The settings panel reports the last completed turn's calls, repairs, and input/
output **characters**, not token estimates. Existing LLM telemetry uses
`operation=chpm` with proposal/validation/repair phases and records provider usage
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
mock-based regression suite. Extended psychology, observer-specific long-term
memory, all-mode support and a dedicated model configuration are later work.
