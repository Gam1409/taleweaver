# Emotional progression: matched-case specification

> Evaluation design, not an executed acceptance report. Baseline limits and gaps
> below refer to the issue #33 investigation; use current [Personality documentation](../chpm-pilot.md)
> and [presentation contracts](../npc-portrait-presentation.md) when constructing a
> new run. Each result must name the tested revision and distinguish proposed
> fixtures, mocked host checks and actual live-model trajectories.

Companion to the [issue #33 plan](emotional-progression-issue-33.md) and
[research decisions](emotional-progression-research.md). These are proposed
fixtures and acceptance contrasts, not results of executed tests.

Use fictional neutral scenarios and independent before-turn snapshots. Preserve
world state, observer scope, effective settings and sampling between variants.
Change only the stated contrast. A case can have several coherent outcomes;
do not assert one required adjective, gesture, emotion label or sentence.

## A. Personal meaning and agency

**A1 — Same event, different stakes.** An archive closes early. One NPC needs
access to keep a promise; another has just completed the task and can leave.
Use authored/current goals as the only difference. Accept differing supported
responses, including relief mixed with concern. Reject a shared reaction derived
only from the event's generic tone.

**A2 — Accident versus intention.** A messenger blocks the archivist's route.
In one variant an observed collision pushed the messenger there; in the other,
the messenger explicitly states an intention to prevent passage. Keep the actual
obstruction identical. Assess whether responsibility affects interpretation;
do not require anger or excuse an obstacle merely because it was accidental.
Neither interpretation may rewrite the recorded movement.

**A3 — Strong feeling, independent choice.** A cautious archivist receives a
credible warning while a personally important document remains in the room.
Compare accessible help with no accessible help. Fear may coexist with approach,
retreat, delegation or preparation when feasible. The character must not choose
the player's action, acquire an unavailable tool or complete an unexecuted plan.

**A4 — Sustained interest and quiet achievement.** An NPC with an authored interest
works on an accessible map. Contrast an unresolved task with a validated completed
milestone. Curiosity, ordinary continued work, quiet satisfaction or a new feasible
question can be coherent. Do not require a new dramatic stimulus, a broad smile,
mandatory journaling or invented success. Completing one task need not remove an
unrelated concern. Include a quiet profile that can initiate valued contact.

**A5 — Felt responsibility versus actual cause.** Preserve the validated fact that
an external storm delayed a delivery. Contrast an NPC's self-blame with a neutral
self-report. The character can express guilt or propose a repair without becoming
the canonical cause. An accusation, denial or confident explanation cannot alter
the recorded event or disclose another actor's private judgment.

## B. Experience, regulation and expression

**B1 — Same feeling, different display purpose.** Preserve an accepted anger
estimate and its source. In one variant the NPC is speaking privately to a trusted
ally; in the other, maintaining a public negotiation serves an active goal.
Both direct and restrained expression remain available. Restraint requires a
plausible purpose if claimed, but not a mandatory explanatory monologue.

**B2 — Same display, different experience.** Two source-supported variants both
permit a civil greeting. One NPC remains hurt by a broken promise; the other is
genuinely pleased. The greeting and portrait simplification must not overwrite
their distinct private experience. Other NPCs can infer only from allowed cues.

**B3 — Attempt versus outcome.** The NPC tries to settle an argument. Contrast an
acknowledged repair with an explicitly rejected apology. Track offered, received
and effective support separately. Even an accepted apology need not restore
trust immediately. Failure must not trigger an automatic calm/reset fallback.

**B4 — Skill versus spontaneous use.** Compare an explicit request to pause and
reconsider with an otherwise identical scene containing no coping instruction.
Measure whether the latter choice occurs for a character-relevant reason.
Instruction-following alone must not be reported as autonomous initiative.
Do not require either variant to use therapeutic vocabulary or write a note.

**B5 — Relationship and momentary feeling.** Preserve a source-supported valued
relationship while contrasting a disagreement with a pleasant reunion. Strong
anger can coexist with care; a warm greeting need not repair a broken promise.
Do not reset relationship beliefs from a single display or force agreement,
forgiveness or a private-state update in the other actor.

## C. Continuity, relevance and source authority

**C1 — Relevant cause behind distractors.** Establish an unresolved broken promise,
then add unrelated valid experience dimensions until the view's eight-record
limit is exceeded. Ask about the pending promise. Record whether the cause and
its personal meaning survived packing. Compare baseline recency selection with
any proposed bounded selection using the same effective input allowance.
An older source remains older; selection cannot refresh its assessed intensity.

**C2 — Exact packing limits and bindings.** Exercise exact-fit and one-character
overflow admission, zero/one/two explanations, omission counts and deterministic
ties. For each visible `state_id`, verify `already_supports_states` still refers
to the intended canonical evidence roots. Reordering cannot disable repeated-root
protection. Include the representative two-NPC repair envelope near 24,000 chars.
Include three valid stored explanations where the second exceeds the remaining
serialized budget but the third fits. Count admitted explanations, not only the
first two candidates considered. Preserve source age and priority; the baseline
probe reproduces this gap with 468 of 512 extra characters sufficient for two.

**C3 — Repeated reminder versus new consequence.** Repeat the same known promise
without new information, then contrast an observed new missed deadline. The
reminder may preserve relevance but cannot become independent grounds for
intensification. The new consequence needs its own valid citation. Neither
variant may invent an event to satisfy current-source admission.

**C4 — Reappraisal without a new event.** Make an old supported incident available
again, with no fresh external consequence. Record separately whether the NPC can
retain a concern, choose a different tactic and propose a new experience update.
The baseline's recall-only update rejection is a contract observation, not a failed
psychological test. Any proposed extension needs an explicit source/lifecycle
contract; do not make this fixture pass by bypassing source validation.

**C5 — Support and trust.** Present the same offer from an ally with observed kept
promises or observed broken promises. Keep the resource and immediate options
identical. A cooperative NPC can rationally decline an unreliable offer. Accepting
help does not automatically establish restored trust or another actor's honesty.

## D. Narration, repetition and delivery

**D1 — Meaningful callback versus copied form.** Hold the unresolved concern fixed
while varying whether prior prose contains repeated stock gestures. Reuse #24
flow metrics. A candidate should retain the concern while permitting new wording,
actions or silence. Lower phrase repetition alone does not establish continuity.

**D2 — Direct and subtle expression.** Use matched scenes with a clearly important
public revelation or a small ambiguous social cue. Both explicit strong emotion
and subtle/subdued expression can be coherent. Do not impose a universal quota
on tears, exclamations, questions, pauses or restraint.

**D3 — Mixed experience, dominant portrait.** Preserve two supported feelings
while requesting one dominant display label. Verify final reply hash, RGB and
intensity consumers. The dominant label is not permission to discard the other
experience or disclose private content to another NPC.

**D4 — Literal voice protocol.** Pass catalog tokens through actual generation,
review/repair and TTS consumers with English and Russian prose. Add other
languages where the consumer path is affected. Translated technical tokens are
protocol failures, distinct from literary weakness. Unknown prose/markup must not
be silently stripped from stored narration.

**D5 — Contextual language, not keyword mutation.** Compare eager anticipation
with feared danger, an explicitly negated feeling with an asserted one, and a
figurative description of an unpleasant exchange with actual dirty equipment.
Use matched English/Russian formulations. Emotion words, metaphors and public
self-reports need contextual interpretation; they cannot directly apply physical
state changes, diagnose a character or establish an observer's private experience.

## E. Privacy, failure and lifecycle

**E1 — Two observers.** Give two NPCs different permitted observations of one
incident. Add a private notebook entry to only one. Check both proposal contexts,
handoffs and actual outcomes. An inferred motive stays an uncertain belief; it
must not reveal another actor's note, private goal or hidden feeling.

**E2 — Technical failure.** Exercise timeout/refusal, malformed or truncated output,
unsupported citation, unavailable subject and over-budget admission. Preserve the
last validated experience. Unknown/unassessed does not mean calm, absent feeling
or a completed regulation attempt. Report the technical cause separately.

**E3 — Story and memory lifecycle.** Reload, retract/edit the source, copy/import,
Undo and Chronicles. Derived experience must follow its existing source/timeline
owner. The private notebook keeps its latest content across story rewind under
the existing contract. An old note cannot resurrect retracted world facts.

**E4 — Modes and partial information.** Cover CHPM off/shadow/live and the relevant
simplified, partial/inactive paths. Normal, streamed, repaired and regenerated
narration must preserve their owners. Regeneration cannot replay actions or game
time. Presentation availability does not activate CHPM or authorize extra actions.

## Measurements and reporting

For each case record the source set, packed context, visible experience bindings,
proposed/accepted appraisal, selected intention, narrator handoff, final prose,
delivery/presentation result and actual state mutation. Diagnostics must remain
bounded and private; no hidden reasoning transcript is needed.

Evaluate personal relevance, continuity, individuality, regulation/display
coherence, source fidelity and player agency separately. Label authored histories,
consecutive generated trajectories, mocked contract tests and live provider
results separately. Record both valid unexpected choices and definite violations.

Use existing CHPM matrix/appraisal and VN integration owners. Prepare a small
paired smoke run before multi-turn expansion. Compare baseline and candidate
from independent copies of the same snapshot; record requests, failures, tokens,
latency, seeds where supported and cases that were not run. A passing JSON/schema
check or a single attractive reply cannot establish the quality claim.
