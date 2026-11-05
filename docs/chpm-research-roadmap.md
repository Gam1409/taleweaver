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
  beliefs from the active projection. Session forks and host transaction integration
  are described below; this is not distributed exactly-once execution.
- Explicit simulation minutes. Clock advancement does not automatically heal
  relationships, change traits or invent events. No affect decay is installed yet.

The current categorical personality profile can be imported explicitly through
`identity_adapter.from_actor`. It preserves the existing traits and goal; it does
not infer Big Five scores from seven unrelated categorical fields. Unknown fields
are not filled with numerical zero. An empty/oversized authored description is a
visible import error rather than an invented or truncated identity.

The core is now connected to the optional **live VN dialogue pilot** through
`host_adapter`, `host_sources` and `host_state`. The pilot still selects intentions
and reviews narration. This integration adds no LLM calls and does not enable CHPM
by default. Off and shadow modes do not advance the new core.

## Host integration: identity, observations and persistence

- The first successful live turn pins the NPC's authored description, categorical
  traits and original goal. Both intention selection and the narrator contract
  receive that identity. Later edits to the mutable NPC card, feelings or player
  requests do not silently replace it. New declared goals/commitments remain in
  the pilot's separate source-bound agenda. Explicit identity migration is not yet
  available; disabling/re-enabling CHPM does not reset the baseline.
- The current witnessed host frame contains the observer's authoritative scene,
  visible co-present NPC IDs, own possessions and known worn item IDs. Changes
  since the previous observation form a separate witnessed source, with unknown
  causes. It excludes hidden actors, other inventories, private memories, scene
  prose and unverified outcomes. See [world perception](chpm-world-perception.md). Approved player excerpts
  and reviewed assistant speech are stored as **reports**, not world facts.
  Observations begin when enabled; past events are not reconstructed automatically.
- The full state lives in `entity_states.__chpm__.minds`: original genesis,
  accepted journal, projection and message bindings. Pending observations remain
  turn-local until the reviewed reply is committed. Failed turns cannot publish
  them. Recovery snapshots and checkpoints include the whole state; restore checks
  projection integrity and session scope before changing live rows.
- Every observation is bound to a saved message, revision and content hash. Before
  the next decision, sources are checked again. Editing/deleting a source rewinds
  that observer to before its earliest affected event, removing the causal suffix
  and dependent pilot speech/agenda. This is conservative invalidation, not a claim
  that unaffected later inferences have been recomputed.
- Copy/export-import explicitly rebinds message IDs and session scope and replays
  events, preserving original identity, beliefs and their citation chains. Missing
  sources remove their dependent suffix. Cached decisions are not copied. These
  are independent session forks, not a distributed branch-merging protocol.
- Settings changes preserve the current core while keeping the pre-turn replay
  baseline separate: observations from a completed reply cannot leak into retry.
  The owner receives counts; full private state is returned only to administrators
  in the existing CHPM inspection API. No new frontend inspection panel is added.
- Limits remain explicit: 32 psychological identities, 256 active events and
  8,192 total archived/active events per observer, with 2,048 beliefs.
  [Capacity admission](chpm-memory-lifecycle.md) now checks a whole-turn reserve
  before CHPM inference, warns in settings and requires an explicit pause/Standard
  selection instead of failing midway or dropping history. Exact archival is
  implemented; semantic consolidation remains future work. Verified replay
  prefixes are cached with bounded memory.
  Model context includes one current host frame and at most
  eight existing subjective beliefs, not the full event journal. Existing input
  character/call limits still apply; more prompt text does not mean free tokens.

## Live cognitive interpretations and local relationship expectations

Live VN proposals now include an explicit `interpretations` array (zero to two).
The same model call proposes candidates and subjective assessments. The host
validates the complete assessment batch **before** intent selection; the reviewed
reply still commits the batch atomically. Shadow retains the older comparison
path. No additional LLM calls are added, and CHPM remains off by default.

`appraisal_context` exposes at most six recent speech/world-change sources with
excerpts of up to 1,000 characters, up to three older 300-character fragments
retrieved by perceived lexical cues, eight recent beliefs and known subject IDs. Excerpts and
omitted counts are labelled. Citations must match the actual visible excerpt,
not a hidden remainder. Beliefs are selected by last accepted interpretation,
not lexicographical ID. The existing input/output limits still apply; this adds
prompt/output tokens despite keeping the number of requests unchanged.

The `local-beliefs-v1` projection keeps separate expectations about **reliability,
competence, benevolence, affection and boundaries**, directed to one known person.
It does not maintain a single relationship score. Alternative explanations and
unknown causes are stored on each interpretation. Revising an existing belief
returns only its ID and new grounds; the host resolves its immutable subject,
domain and proposition, avoiding model rephrasing of canonical text. Counterevidence adds a challenge
without deleting earlier support. Original identity and unrelated relationships
remain unchanged. There are no confidence numbers, automatic forgiveness, affect
updates or consent inference in this schema.

The narrator receives the current turn's accepted assessments as private,
subjective context. The decision trace records their evidence IDs. Subsequent
turns can refer to those beliefs. Rewind, edited-source invalidation, copy and
import retain the same provenance rules, including alternative/unknown metadata.
Old snapshots without the additive fields continue to load.

Limits of this stage are deliberate: a correct citation does not prove that the
model interpreted it correctly. Exact duplicate propositions share an ID, but
semantic paraphrases are not automatically merged. Repeated source roots are not
new evidence; distinct messages repeating a claim can still have distinct host
roots. Their count is **never** treated as independent corroboration or calibrated
confidence. Live selection now adds `initiative-gated-v1`: independent intentions
take priority over unsupported clarification. A question requires a specific gap
with two available conditional actions, and no equally useful independent option.
Permission to continue speaking is excluded by the narrator/reviewer contract.
Goal alignment and the meaning of the gap remain model proposals, not independently
calibrated psychological utility or a formal proof of semantic necessity.
This is a source-bound qualitative appraisal layer, not full EMA appraisal,
emotion dynamics, or measured human-like relationship development.

## Research matrix coverage

Live proposals additionally require [source-bound candidate motives](chpm-motivation.md).
Before selection, each alternative references this observer's pinned identity,
active agenda and/or accessible experience, including at least one supporting
identity/agenda motive. The host checks reference availability and consistency
with quoted goal alignment; it preserves competing tensions and reports/belief
status. The existing prose review sees the selected reasons. This is a causal
trace contract, not independent semantic verification or calibrated motive ranking.
No extra call or numerical trait/relationship update is added.

| Matrix reference | Implemented scope | Remaining limitation |
|---|---|---|
| V07, V50–V52; architecture §4, personality development | Preserved authored identity, labelled trait model and source revision | Big Five/HEXACO measurement and evolving self-narrative not implemented |
| V30–V31, V34; TR03–TR04 | Live source-bound interpretations, roots, alternatives, unknowns and retained challenges | Citation correctness does not certify meaning; no calibrated posterior; not complete TR04 |
| V42–V45; T13 | Directed qualitative relationship expectations; tests preserve other people/domains | Numerical relationship/affect dynamics are not implemented |
| V57, V59; T08, T12, T22 | Observations versus inference/reflection; root deduplication | Retrieval/consolidation policies are not complete |
| V65–V69; T01, T03, T23–T25 | Revision/cursor/event checks, atomic host persistence, replay, validated restore, rewind and session copy | Distributed branch merge and accepted RNG tape are later work |
| T02, T06 | Other observers' unavailable citations are rejected; live host frame exposes own scene, own possessions and visible NPC IDs | Speech perception/review still depends on model interpretation |
| T04, T27–T28 | No wall-clock transitions, model failure event, or model dependency | Catch-up scheduler/pending barrier integration not implemented |
| T09 | Independent conflicting evidence produces a tracked challenged belief | No claim of empirical accuracy of belief revision |

Tests in `tests/test_chpm_core.py`, `tests/test_chpm_host_*.py` and
`tests/test_chpm_appraisal*.py` establish only
those stated program invariants, including real VN transactions with mock models,
source edits, failed turns, settings, snapshot restore, session copy/import,
invalid interpretation batches and a 40-turn history with all seven authored traits.
They do not establish all Gate 0/1 requirements or psychological validity. In
particular, T20 remains probabilistic for unrestricted prose: a valid source
reference does not prove correct interpretation of a speech act.

## Evaluation scope

The earlier comparison harness has 41 authored scenarios and records failures,
cost and accepted text separately. After the owner stopped the model, the endpoint
became unavailable during the run; later transport failures are not psychological
test failures. The owner later supplied a new endpoint for the bounded appraisal
probe described in [the appraisal evaluation guide](chpm-appraisal.md).

The new 12-step trajectory fixture covers pressure, apology, earned cooperation,
breach, attempted identity rewrite, a trauma reminder, repair and an invitation.
Accepted decisions, sourced memory and agenda carry forward using the existing
pilot's production `finish` boundary in an isolated in-memory host. Failed steps
do not become memories or personality events. External events are authored;
retrieval is simulated. This isolated evaluation harness does not yet exercise the
new live host adapter: its authored host scene goes to the narrator, while cognition
receives speech observations. The new production adapter adds observer-local world state and differences,
not a complete witnessed world-event vocabulary. This trajectory has only mock-based tests so far, not a
completed live run or proof of psychological development.

## Next implementation slices

The [exact archive and lexical subjective-memory view](chpm-memory-lifecycle.md)
are implemented. Total storage remains finite; semantic consolidation is future work.

1. Evaluate the new source-bound candidate motives with controlled counterfactual
   pairs and source ablations. Structural grounding is implemented; semantic goal
   relevance and evidence quality still need calibration. Distinguish fear, desire,
   attraction, consent, trust, affection and displayed expression before introducing
   numerical transition weights.
2. Expand the host's observer-filtered world-event vocabulary and exercise it in
   the isolated trajectory evaluator. Keep fact, report, interpretation, intention
   and outcome distinct; do not promote arbitrary narration into observations.
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
