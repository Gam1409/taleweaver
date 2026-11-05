# CHPM research implementation map

The owner's [architecture and matrix](research/chpm/README.md) are the versioned
references for this work. Original files are retained unchanged with SHA-256
checksums. Their research claims and planned test statuses are not implementation
claims for TaleWeaver.

## Development objective

NPC decisions should follow their own authored identity, goals, accessible
experience and changing subjective state. Player satisfaction is not an objective
function. Agreement is not automatically a defect; disagreement is not proof of
autonomy. Literary quality is a separate evaluation axis from causal continuity.

The research document explicitly fixes traits in the MVP. Later personality
development must be a separate, source-bound consolidation process, preserving the
original identity and considering alternative explanations. A transient emotion,
attraction, one incident or a player's instruction must not rewrite the baseline.

## Implemented foundation: source-bound subjective state

`backend/engine/chpm/core/` is pure code: Pydantic and the standard library only,
with relative imports within the core. It has no game, DB, network, Concordia or
LLM dependency. It is packaged with TaleWeaver for now, not published as a separate
library. It provides:

- An immutable authored identity and explicit world/branch/observer scope.
- Host-supplied witnessed observations and reported speech, distinct from model
  inference and reflection. Observation availability and root IDs are the host's
  responsibility; the core cannot certify that a malicious host told the truth.
- Exact, accessible source citations for each interpretation. The model-facing
  `accept_interpretation` port cannot create host observations, choose new root
  evidence IDs, advance time or patch personality/trust.
- Subjective propositions scoped to a particular subject and domain. A new
  interpretation can support or challenge a proposition; both histories remain.
  An existing belief ID cannot silently become a different proposition/person.
- Root-source aggregation: relaying a rumor or reflecting on an inference does
  not create independent evidence. Counts never become probabilities. Probability
  remains `None`; this is not yet a calibrated belief-strength update rule.
- A deterministic pure reducer with revision, cursor and event-ID checks.
  Duplicate delivery is a no-op; conflicting reuse of an ID fails. A transition
  returns a complete new snapshot without mutating the previous snapshot.
- Journal replay, original identity/scope checks against host-supplied genesis,
  complete projection validation on restore, and reconstruction
  through a chosen cursor. Rewind removes later observations and their derived
  beliefs from the active projection. Branch creation/host transaction coordination
  remain integration work; this is not distributed exactly-once execution.
- Explicit simulation minutes. Clock advancement does not automatically heal
  relationships, change traits or invent events. No affect decay is installed yet.

The current categorical personality profile can be imported explicitly through
`identity_adapter.from_actor`. It preserves the existing traits and goal; it does
not infer Big Five scores from seven unrelated categorical fields. Unknown fields
are not filled with numerical zero. An empty/oversized authored description is a
visible import error rather than an invented or truncated identity.

This new core is **not yet wired into live turn selection**. The existing optional
dialogue pilot still owns current session behavior, memory and agenda. This avoids
silently replacing that implementation before the new transition policies and host
adapters are ready. No additional inference is triggered by importing this core.

## Research matrix coverage

| Matrix reference | Implemented scope | Remaining limitation |
|---|---|---|
| V07, V50–V52; architecture §4, personality development | Preserved authored identity, labelled trait model and source revision | Big Five/HEXACO measurement and evolving self-narrative not implemented |
| V30–V31, V34; TR03–TR04 | Source-bound subjective propositions, roots and retained challenges | No calibrated posterior or reliability estimation; not complete TR04 |
| V42–V45; T13 | Subject/domain-local belief records; tests preserve unrelated records | Numerical relationship dynamics and affection are not implemented |
| V57, V59; T08, T12, T22 | Observations versus inference/reflection; root deduplication | Retrieval/consolidation policies are not complete |
| V65–V69; T01, T03, T23–T25 | Revision/cursor/event checks, replay, validated restore, rewind | Full host persistence, cross-branch forks and accepted RNG tape are later work |
| T02, T06 | Other observers' unavailable citations are rejected; core has no hidden-world input | Host visibility filtering remains essential |
| T04, T27–T28 | No wall-clock transitions, model failure event, or model dependency | Catch-up scheduler/pending barrier integration not implemented |
| T09 | Independent conflicting evidence produces a tracked challenged belief | No claim of empirical accuracy of belief revision |

Tests in `tests/test_chpm_core.py` establish only those stated program invariants.
They do not establish all Gate 0/1 requirements or psychological validity. In
particular, T20 remains probabilistic for unrestricted prose: a valid source
reference does not prove correct interpretation of a speech act.

## Evaluation status after live testing was stopped

The earlier comparison harness has 41 authored scenarios and records failures,
cost and accepted text separately. After the owner stopped the model, the endpoint
became unavailable during the run; later transport failures are not psychological
test failures. No new live calls are authorized by the offline work described here.

The new 12-step trajectory fixture covers pressure, apology, earned cooperation,
breach, attempted identity rewrite, a trauma reminder, repair and an invitation.
Accepted decisions, sourced memory and agenda carry forward using the existing
pilot's production `finish` boundary in an isolated in-memory host. Failed steps
do not become memories or personality events. External events are authored;
retrieval is simulated. The current dialogue pilot passes speech observations to
cognition, while the authored host scene goes to the narrator; a direct witnessed
world-event adapter is still missing. This is a known causal-input gap, not a
completed psychology pipeline. This trajectory has only mock-based tests so far, not a
completed live run or proof of psychological development.

## Next implementation slices

1. Connect an observer-filtered host event adapter and atomic host persistence to
   the new core. Keep world fact, report, interpretation, intention and outcome
   separate; do not promote arbitrary narration into confirmed observations.
2. Introduce versioned, explicit subjective appraisal and relationship policies.
   Keep alternatives/unknown, subject and domain locality, and distinguish fear,
   desire, attraction, consent, trust, affection and displayed expression.
3. Integrate competing goals/commitments and causal intent selection on controlled
   candidate sets. Record policy reasons; do not ask the LLM to retroactively invent
   a motive for the chosen action or use player approval as reward.
4. Add calibrated affect/needs transitions with simulation-time tests and ablations.
   Numerical coefficients are engineering hypotheses until measured. General
   affective arousal is not automatically sexual desire or agreement.
5. Consider relationship-specific attachment, habits and trait development only
   after the simpler mechanisms have independent benefit and identifiable effects.

The research document's distinction between engineering invariants, internal model
behavior, psychological validity and artistic quality applies throughout.
