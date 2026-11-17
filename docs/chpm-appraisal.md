# CHPM qualitative appraisal stage

Live VN cognition accepts bounded subjective interpretations in its existing
candidate-generation call. Nothing is enabled by default. Standard mode and the
Observe comparison remain available. The current wire protocol uses separate
`new_beliefs` and `belief_revisions` arrays; the host converts both to canonical
interpretation events without changing the stored reducer contract.

The current model wire selects evidence IDs. Each visible excerpt is displayed
once as exact `fragments` of at most 300 characters. Belief, experience and
intention-change citations return `fragment_id`; development citations return
`episode_id`. Motives already select catalogue IDs. The host supplies canonical
source IDs, exact quotations and provenance before the existing validators run.
The required `reference_scope` binds these selectors to this observer, source
window and host attempt/operation. Request metadata remains separate from the
semantic decision cache. Legacy canonical source/quote records keep their strict
read, replay and lifecycle contracts; they are not accepted as modern responses.

```mermaid
flowchart LR
  A[Observer-visible speech and original identity] --> B[Bounded evidence and belief window]
  B --> C[One LLM call: interpretations and candidates]
  C --> D[Exact source and subject/domain validation]
  D --> E[Pending belief revision and initiative-gated intent selection]
  E --> F[Narrator with private subjective context]
  F --> G[Existing reply review and optional repair]
  G --> H[Atomic reply and state commit]
```

The core retains supporting and challenging evidence, alternative explanations and
unknown causes. Reliability, competence, benevolence, affection and boundaries
are separate propositions about a particular person. An accepted interpretation
can be wrong; it remains an inference and cannot become a world event or edit the
original character. A malformed proposal or fabricated citation fails the whole
turn, preserving its previous state.

Inputs normally expose up to six recent speech excerpts (1,000 characters each),
three historical slots and eight ordinary beliefs. All current approved evidence
is retained even when it exceeds the recent-source count. Ordinary beliefs are
filtered before applying the count limit; developmental propositions cannot crowd
them out. Present people explicitly mentioned in the approved request, current
speakers, lexical overlap and evidence recency guide selection. This is local
retrieval, not a psychological confidence score or semantic search.

Historical slots first retain available opposing/supporting grounds for selected
beliefs; remaining slots use observer-local episodic recall. A single available
slot favors counterevidence. `basis_for` labels the interpretation's stance toward
a proposition, never the truth of the reported event. Short sources retain their
full wording; longer sources use the cited passage when it fits, otherwise the
exact quote with `excerpted=true`. Relevant grounds outside a historical source's
prefix replace that prefix, not current evidence. Missing recall proves no absence.
Explicit agent pins keep their existing separate limits and priority.

Output allows two interpretations with two citations each. These limits bound
the protocol, not the accuracy of retrieval or psychological inference.
The existing settings still bound total input characters and output tokens. Calls
per successful Staged live turn with agent rounds off remain N + 2, or N + 4 with
narration repair, plus the normal narrator. Tool rounds, shared proposal repair,
Integrated decisions and recovery follow the [workflow guide](npc-decision-workflows.md).

Current live selection uses `motivated-choice-v2` with the existing clarification
gate; see [motivation and arbitration](chpm-motivation.md). The older comparison
path retains `goal-first-v1`. The LLM still supplies intentions, goal alignment and
conditional dependencies. Matching quotations and structurally valid dependencies
do not prove semantic relevance. There are no numeric trust/affection changes, spontaneous trait edits,
automatic trauma recovery, or confidence inferred from source counts.

## Independent choice and necessary questions

An unsupported `CLARIFY` is not an eligible live preference merely because the
generator labels it goal-supporting. A `question_gate` must name a specific missing
external fact or player's intention and two distinct answers mapped to two other
offered actions. Duplicate, unavailable or recursively questioning branches do not
unlock clarification. Actions blocked by that unresolved question remain unavailable.

Current `motivated-choice-v2` accepts the model's eligible, source-grounded preference.
Goal labels and motive-set dominance remain diagnostic rather than a calibrated
priority over that preference. Earlier `initiative-gated-v1` favored independent
goal-tier progress; it is not the current live selector. Silence, cooperation,
refusal and personal goal tradeoffs remain possible when properly offered and
grounded. The trace records `selection_reasons` and the proposed `question_gate`.

Generic permission to continue talking/writing is excluded from the contract.
The narrator must express the chosen intention without handing that choice back
to the player, and the reviewer must reject added generic permission requests.
Specific player choices, including accepting an offered arrangement, remain theirs.
This is not a blanket ban on questions, dialogue invitations or negotiation.
An RP question can itself express initiative through curiosity, care, suspicion,
affection or bargaining. It does not require the information-gap gate unless it
defers the choice of intention. Generic approval-seeking cannot bypass that gate
by being labelled INITIATE. Question frequency alone is not a rejection criterion.

The gate's semantic classification and the prose review still depend on the model.
A dishonest/mistaken dependency can pass structural validation, so the live probe
and adversarial review checks measure residual errors rather than claim a perfect
semantic guarantee. These are explicit engineering policies, not proof of human
psychological fidelity.

## Reproducible live probe

Run only against an explicitly approved endpoint:

```bash
python -m backend.engine.chpm.evaluation.appraisal_probe \
  --endpoint https://YOUR-ENDPOINT/v1 \
  --output /tmp/chpm-appraisal-unique-run
```

This uses the existing router and inference admission controls with a temporary
configuration; it does not edit accounts or game sessions. The five fixed cases
cover a missed promise, an alternative cause, a repeated report, attempted identity
rewrite and a claimed completed action. Every input is an authored report, not a
confirmed world outcome. Four steps exercise cognition only; the final step also
uses the production narrator contract, reply review and in-memory `finish` boundary.
This is not an end-to-end live VN run or a substitute for a psychological evaluation.

The probe writes separate JSON records with decisions, before/after state, actual
model text, timing and provider token usage where available. It refuses to overwrite
an existing output directory. Failed cognition does not enter the accepted history.
Ordinary execution uses seven logical calls; a final repair can add two. Network
retries/fallback may involve additional transport attempts. The first four fixture
steps are deliberately not spoken NPC dialogue and cannot measure conversational
repetition or narrator fidelity.

Offline tests additionally cover unrelated relationships, exact citation boundaries,
unavailable subjects, invalid JSON, unauthorized state patches, 40 turns with all
seven categorical traits, atomic failure, old snapshots and copy/rewind provenance.
Passing these tests establishes software invariants, not psychological accuracy.
