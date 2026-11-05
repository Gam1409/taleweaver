# Final pilot validation before merge

This is an acceptance plan, not a claim that CHPM simulates human psychology.
The pilot remains optional. No new live run starts until the owner supplies an
available model endpoint; old paid instances must not be polled automatically.

## Completed after the dual-model probe

- Structured calls inspect provider completion metadata even with file logging off.
  Explicit `length`/`max_tokens` completion is rejected even if its prefix parses.
  A syntax-invalid JSON response at its token cap, without a reported finish reason,
  is also rejected as output exhaustion. Missing or ambiguous metadata remains unknown.
- Exhaustion does not consume another request at the same insufficient budget.
  A complete response with an ordinary JSON/schema/semantic error still gets the
  existing one shared repair. No limits are raised silently; transport errors do
  not get that repair. Evidence and commit checks remain unchanged.
- Matrix artifacts include the effective output limit, reported finish reason and
  number of completion records. Multiple records are not collapsed into an invented
  single finish reason. `--output-tokens` sets an explicit cognitive budget and the
  temporary endpoint's role limits; with `--user`, saved role caps still apply.
- Matrix runs stop after a failed transport call, keeping completed results and
  `completed` versus `planned` counts. Remote completion must be checked before retry.
- Fifteen continuity fixtures keep one authored identity across five contexts for
  each of three profiles. The same innocent request is compared across an unfamiliar
  interaction, positive reported history, a reported boundary breach and visible time
  pressure. A fifth variant adds a demand for unconditional compliance.
- Motive instructions clarify that effect signs must agree with the explanation;
  reserved speech is not mandatory refusal and friendliness is not mandatory obedience.
  This is guidance, not a deterministic semantic validator.

## Offline checks

Run CHPM and logger/usage regressions, then the full backend suite and type checks.
Regression cases include completed-invalid JSON, explicit truncation, missing usage,
nested/parallel metadata observers, unchanged state on exhaustion and counterfactual
fixtures retaining all identity fields. These checks use mocks, not remote models.

## Paid run, in bounded batches

First use `matrix_cli plan` to inspect cases and quotas without model discovery.
Keep a separate run ID for every model, batch and repetition. Record the exact
advertised model, hardware, token limit, timeout, and whether the server is cold.
Do not compare changed prompts or budgets as a controlled model-only comparison.

| Batch | Cases | Maximum logical calls |
|---|---|---:|
| Basic | `everyday-ordinary-n1-h0`, `everyday-pressure-n1-h0` | 14 |
| Perception and history (`--suite stress`) | `short-speech-long-actions`, `dense-actions-h3`, `recall-superseded-h40` | 21 |
| Character (`--suite continuity`) | all five `continuity-reserved-*`, `continuity-warm-routine`, `continuity-skeptical-routine` | 49 |
| Cast | `science_fiction-fear-n3-h12`, `fantasy-conflict-n20-h40` | 18 |

That is 14 cases and at most 102 logical calls, not a fixed token cost or a promise
that every call is needed. Stop after the basic batch if budget/transport is broken.
Do not rerun all cases simply because one fails. Additional repetitions and the
full 360-case matrix are separate research, not a hidden part of this budget.
Only active interlocutors are processed deeply in the cast batch; twenty present
NPCs are not twenty simultaneous full cognitive evaluations.

For a larger response limit, first measure one case. At 20 output tokens/second,
4096 output tokens alone can take over 200 seconds. Increasing a client timeout
does not increase a proxy's limit. This patch does not introduce streaming transport
or claim to disable server-side reasoning on every OpenAI-compatible server.

## Behavioural review, separate from technical success

1. Retain short speech and consequential attempts; exclude private thoughts.
2. Prefer current corrections over old reports while keeping unknowns explicit.
3. Trace each decision to accessible sources and this NPC's own motives. Agreeing
   can fit the portrait; refusing can fit it too. Neither is a universal target.
4. Compare the paired contexts. The same decision can remain appropriate across
   them; changes need contextual reasons, not merely a different action label.
5. Inspect `selection_reasons`, `motive_dominance` and `candidate_motives` explicitly.
   A deterministic hash tie is repeatability, not psychological calibration.
   Different fixture/source identifiers can change tie outcomes; never score that
   alone as evidence of sensitivity to a relationship or time pressure.
6. Distinguish brief speech from refusal, concerns from vetoes, attraction from
   agreement and temporary stress from a rewritten personality.
7. Check that narration preserves the decision and does not invent player authority,
   completed world actions or consequential facts. Relevant negotiation questions
   are allowed; permission merely to continue speaking is not a requirement.
8. Reject corrupted/incomplete output without changing saved identity or state.

Merge readiness requires engineering checks to pass and an explicit review of live
failures and limitations. It does not require every NPC to make the reviewer's
preferred choice. Report technical success and psychological assessment separately.
After the last request, confirm both remote queues are idle and notify the owner
immediately, before spending time writing the final report.

## Scope after this pilot

Semantic consolidation/forgetting, a separate attachment model, evolving self-narrative,
calibrated psychological utility and a comprehensive semantic motive validator remain
research work. Exact archival, lexical recall and sourced qualitative developments
must not be described as completed substitutes for those systems. The next product
work after accepted live validation and merge is the settings/debug interface layout
and interaction flow, independently of those research extensions.
