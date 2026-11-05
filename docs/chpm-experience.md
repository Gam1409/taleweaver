# Source-bound affect and need appraisals

`qualitative-experience-v1` adds a separate temporary-state layer to live CHPM.
The existing proposal call may return zero to two experience hypotheses alongside
relationship interpretations and candidates. Missing/empty output means no new
estimate, never an assumed neutral state. This adds input/output tokens, not a
new model request. Original traits, values, goals and relationship beliefs are
not overwritten by an experience event.

## Representations and grounding

- Affect: fear, anger, sadness, joy, shame, interest and general arousal. Arousal is
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

## Time, persistence and expression

The latest appraisal per channel/dimension/subject is projected separately; all
accepted events remain in the exact journal/archive. At most 128 dimensions are
retained per observer. Admission reserves two potential new dimensions and two
events before inference; a full turn reserves 53 events in total.

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
