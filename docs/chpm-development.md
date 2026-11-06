# Slow developmental reflections

Policy `slow-tendencies-v1` adds optional source-bound qualifications to behavior.
It does not rewrite genesis, authored traits, values or goals. The baseline stays
available alongside current feelings, directed beliefs and declared goals.

## What can develop

| Kind | Scope | Engineering admission gate |
| --- | --- | --- |
| Conversational habit | One observed scene | Three distinct messages across at least one game day, quoting the NPC's own speech |
| Relationship expectation | One person and relationship domain | Three distinct messages across at least one game day, including that person's observed speech |
| Trait tendency | One existing authored trait | Three distinct messages across seven game days, the NPC's own speech in at least two scenes |

These are conservative engineering thresholds, **not psychological measurements**.
Passing them does not prove causation, generalization or durable personality change.
The model must state alternative explanations and unknowns. Player instructions
about personality cannot serve as the NPC's own behavior. Physical habits,
diagnoses, numerical Big Five scores and automatic identity migration are absent.

## Evidence and lifecycle

Up to nine dated speech episodes are sampled across available history. In busy
histories, up to three slots retain the observer's own reviewed speech and up to
three retain the current relevant person's speech (the player when unspecified).
Each group keeps its chronological endpoints and prefers a different scene for
the middle example. Remaining slots favor lexical relevance and recency; the
final view remains chronological. This prevents uniform sampling from losing all
of the NPC's own dated speech. Excerpts are at most 200 characters. A source
needs an observer-local host frame to establish its scene. Missing dates/scenes
are not guessed. Sampling can miss relevant episodes and counterexamples; omission
is not evidence of absence.

At most one reflection is proposed per cognitive call, using the existing call.
Its supporting and opposing citations are exact excerpts. Support and challenge
become ordinary core `Interpret` events under `development.*` domains. They retain
root provenance and participate in exact replay, archives, fork and retraction.
Repeating the same roots is not new support. New support for the same proposition
is limited to once per game day; counterevidence can challenge sooner.

One proposition is retained per habit scene, trait or directed relationship domain.
A paraphrase cannot replace that proposition and hide its counterevidence.
Revision identifies the existing proposition without rewriting its statement.
This intentionally limits the vocabulary of development; richer self-narrative
revision needs another explicit policy.

The narrator and cognitive model receive at most four recent relevant tendencies,
labelled tentative or contested. Habits are shown only in their originating scene.
These are contextual qualifications, not new numerical selection weights.
Unrelated traits and relationships must remain distinct. Semantic fidelity still
depends on proposal and review quality; typed citations cannot prove it.

## Budgets and failure

Optional consolidation first tries to fit within the configured input budget.
If only that optional view is too large, it is deferred and the decision records
`development_status=deferred_input_budget`. Required identity/current context still
fails visibly if oversized. Other validation errors are never swallowed as budget
deferrals. Invalid proposals do not partially mutate the saved state.

No extra LLM request is introduced. Output can grow by one reflection; its input
schema and source samples consume part of the existing per-request budget. The
normal turn reserves three possible new beliefs and 53 events in total.

The source research files remain unchanged under `docs/research/chpm/`. This
implementation is a qualitative pilot, not the complete research specification.
