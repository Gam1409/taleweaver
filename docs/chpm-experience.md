# Source-bound affect and need appraisals

`qualitative-experience-v1` adds a separate temporary-state layer to live CHPM.
The existing proposal call may return zero to two experience hypotheses alongside
relationship interpretations and candidates. Missing/empty output means no new
estimate, never an assumed neutral state. This adds input/output tokens, not a
new model request. Original traits, values, goals and relationship beliefs are
not overwritten by an experience event.

## Representations and grounding

- Affect: fear, anger, sadness, joy, shame, interest, general arousal and optional
  sexual desire. Arousal is
  general activation, not sexual desire or consent. Affect can concern a known
  subject or have no named target. Several feelings may coexist.
- Need satisfaction and need frustration: separate channels for autonomy,
  competence, relatedness, rest and safety, scoped to this observer. Low
  satisfaction does not automatically mean high frustration. This engineering
  vocabulary is neither an exhaustive taxonomy nor a physiological model.
- Levels: absent, low, moderate, high, always labelled subjective appraisal. No
  numeric probabilities, clinical diagnoses, trait patches or consent updates.

Each proposal needs exact visible citations, at least one current observed trigger,
this NPC's authored identity/active agenda basis, a short explanation, alternatives
and unknowns. Old recall alone cannot refresh or intensify an experience. The pure
reducer checks original identity and exact evidence, propagates existing roots,
and rejects repeated grounds as a new update. A repeated event ID is idempotent.
This validates provenance, **not the psychological correctness of the estimate**.
A quoted demand can be interpreted as pressure; it does not establish that the
observer has the feelings the speaker attributes to them.

Canonical body/owned-garment conditions and observer-accessible scene facts can
also ground an estimate through `host_observation` sources. They are individual
facts from the existing full host frame, recorded in the same journal. Excerpts
carry their canonical target/body-part or scene binding, so a garment condition
is not presented as an unspecified condition of its owner. A source
is reused while its canonical content is unchanged; changing another inventory
entry, moving rooms with the same injury, or advancing the clock does not create
fresh grounds. Scene identity and status remain part of a scene fact's grounds.
First observation time is retained in its original event, not reset on each turn.

`currently_observed=true` means the latest frame for this input still establishes
that specific fact. It does not mean the fact just happened: `current_turn` retains
the original source-turn meaning. Such a fact can receive its first appraisal
later, but reused roots cannot refresh/intensify an existing estimate. The source's
`already_supports_states` points to exposed experience-state IDs that already use
those grounds. A complete `host_frame` is context, not an experience citation;
otherwise an unrelated change could make all its old facts appear independent.

Up to four current fact excerpts are exposed; omissions are explicit and the full
canonical frame remains saved. New facts are admitted in bounded batches, with
body and scene candidates interleaved. Facts unavailable to the observer, other
rooms' processes and scene facts needing confirmation cannot become current
triggers. Missing state does not mean healed, clean or calm. A confirmed changed
condition or observed process ending supplies different grounds. This preserves
the existing reviewed-commit, copy/import and rewind ownership, without a new
model/embedding call, memory store, automatic emotion or physiological timer.

`sexual_desire` is an optional affect appraisal, not a required personality field.
It can exist without a sexual act. `about_id` names a known target or remains null
when no target is specified. An omitted appraisal is unassessed; `level=absent`
is an explicit sourced estimate of absence. General arousal never creates this
dimension automatically. Desire can coexist with distrust, conflicting goals or
a decision not to act. It does not grant consent, imply affection, compel approach,
or rewrite baseline traits. The existing current-evidence, freshness, rewind and
reviewed-commit rules apply without an extra model call. No mature-content policy
or image-generation prompt is changed by this addition.

## Time, persistence and expression

The latest appraisal per channel/dimension/subject is projected separately; all
accepted events remain in the exact journal/archive. At most 128 dimensions are
retained per observer. Admission reserves two potential new dimensions and two
events before inference. Admission also reserves at most four new state sources;
a full turn reserves 75 events in total. Existing storage limits are unchanged.

Up to eight recent dimension records are exposed in the cognitive/narrator context.
For 30 simulation minutes they are labelled recent appraisals; afterwards the
last estimate is historical and **current intensity is unknown**. This horizon is
an explicit engineering freshness policy, not a measured emotional half-life.
Elapsed time does not modify intensity, forgive a breach, satisfy a need or heal
trauma. Unknown is not absent. Quantitative affect decay, bodily resource dynamics
and learned regulation are not implemented in this version.

The narrator receives private context, not an instruction to recite state labels
or display every feeling. Polite expression may coexist with anger. Temporary
states do not authorize new actions, private revelations or a new personality.
The existing review checks the selected intention and these distinctions, but the
reviewer remains fallible.

Experience updates commit only with reviewed narration. A failure leaves the old
state unchanged. Restore, source edits, rewind and session copying preserve or
retract them through the same source-bound event history. Technical/model failures
never become feelings. Fixed traits remain the historical baseline; durable trait
development uses the separate [evidence and alternative-explanation policy](chpm-development.md).

## Verification and remaining validation

Tests cover mixed states, independent need channels, exact citations, rejected
batches, historical-only triggers, duplicate grounds, elapsed-time uncertainty,
unchanged identity/relationships, forked references and real VN commit/rollback
with mock models. The user has stopped the live model to avoid hosting cost;
behavioral calibration of these new contracts is deferred until it is available.

The schema omits generated display titles, not constraints, and prompt JSON uses
compact UTF-8. The motive catalogue references the already supplied pinned
character instead of repeating it. Existing input limits are still enforced;
there is no automatic increase of saved limits. Long/complex histories may still
need a deliberately larger configured budget.

For long histories, `historical-view-budget-v1` tries progressively smaller optional
history views before requesting the model. It preserves pinned identity, current
observations, active agenda and saved settings; it labels the chosen tier and
omitted dialogue/history. Historical quotation limits are maxima, not a promise
that every configured entry fits every request. Canonical history is untouched.
If required context still exceeds the budget, no request is sent. The cognitive
input refers to beliefs once through `appraisal_context`, rather than repeating
raw belief/root structures in the host frame.
