# Emotional progression evaluation

The `emotion` suite extends the existing CHPM cast matrix. It exercises production
perception, context packing, `cognition.deliberate()`, narration, review and commit
without modifying a game database. It does not train a model or rate psychological
quality automatically.

The [research synthesis](engineering/emotional-progression-research.md) explains
the design decisions. The broader [case specification](engineering/emotional-progression-cases.md)
also includes offline privacy, lifecycle and failure tests; its 24 specifications
are not the same thing as the 24 executable model contexts below.

## Matched contexts

Six contrasts each have two variants in English and Russian: **24 contexts,
12 matched pairs**. Character identity, goals, profile, current question and cast
remain the same within a pair. Only the stated context changes.

| Contrast | Variants | Review question |
| --- | --- | --- |
| Obstruction | Accident / deliberate blocking | Does perceived intent affect personal interpretation without rewriting the obstruction? |
| Support | Offered / report delivered | Does the NPC distinguish help, delivery, verification and emotional repair? |
| Display | Public / private discussion | Can the same reported concern support distinct, grounded expression without compulsory masking or composure? |
| Detour | One / forty authored history entries | Does the earlier unresolved concern remain available and relevant without becoming a new incident? |
| Mixed experience | Positive milestone with an unresolved / corrected record | Can satisfaction coexist with hurt, and does the actual correction change only what it establishes? |
| Reliability | Kept / broken earlier arrangements | Does sourced reliability inform choice without requiring acceptance or refusal? |

Support and mixed-experience cases contain two controlled NPCs. The other cases
contain one. A perception or scheduling result may activate fewer NPCs; inspect
the saved `active` and `inactive` lists rather than assuming every actor spoke.

History is authored fixture speech, not generated prehistory or verified current
inner state. The suite does not seed a feeling as a world fact. Public test events
are explicitly assigned by the fixture author. A sourced self-report remains a
self-report, and other observers do not acquire access to private experience.
The long case contains forty authored NPC history entries, not forty consecutive
model-generated interactions.

## Plan without a model

```bash
poetry run python -m backend.engine.chpm.evaluation.matrix_cli plan --suite emotion
```

The manifest includes exact case IDs, histories, per-case rubrics and logical
request allowances. The full suite permits at most **176 logical calls per arm**
with default agent rounds. This is an upper bound including repair allowances,
not a request count or price estimate. Transport retries and model discovery are
outside that logical-call count; measure them separately when reporting cost.

For a first smoke comparison, select a pair explicitly:

```bash
poetry run python -m backend.engine.chpm.evaluation.matrix_cli plan \
  --suite emotion \
  --case emotion-display-public-ru \
  --case emotion-display-private-ru
```

## Explicit model run

Use a current endpoint configured locally in `TALEWEAVER_EVAL_ENDPOINT`; keep
credentials out of command arguments and published artifacts. A run requires a
new run ID, an endpoint or saved user configuration, and an explicit quota.

```bash
poetry run python -m backend.engine.chpm.evaluation.matrix_cli run \
  --suite emotion \
  --case emotion-display-public-ru \
  --case emotion-display-private-ru \
  --endpoint "$TALEWEAVER_EVAL_ENDPOINT" \
  --run-id emotion-display-candidate \
  --max-total-calls 14
```

The existing artifact owner writes below `log/chpm-evaluations/`, using validated
paths and its existing 32 MiB results-file limit. Artifacts are private diagnostic
input, not game assets or material to attach automatically to a PR. Proposal and
proposal-repair audits include the exact bounded `experience_context` alongside
the visible evidence and packing metadata. The audit allowlist excludes the full
private notebook; returned model text can still contain subjective material and
must be reviewed before any sharing.

The executor stops after an incomplete transport result. Inspect remote completion
before running again; do not treat a timeout as permission for unlimited retries.

## Baseline and candidate comparison

Use independent checkouts/snapshots with the same evaluation harness and fixtures.
For an older baseline, apply only the evaluation-harness changes in that isolated
checkout; keep its runtime owners unchanged. Record the engine revision and the
harness revision/diff separately. Match model ID, effective limits, sampling,
language and before-turn state; record seeds when the provider supports them.

The new reason-packing regression demonstrates a host defect using valid
quote/backslash-heavy strings. Natural-language contexts need not trigger that
boundary. Absence of a prose difference in this suite therefore would not negate
the packing fix, and a packing test passing cannot establish better prose.

Inspect each stage separately:

1. Allowed sources, their ownership and omissions.
2. The exact packed experience, reason text and historical/current status.
3. Proposed versus accepted appraisals and selected intentions.
4. Narration and review results, including failed repairs.
5. Committed state, final prose and any available delivery metadata.

Rate personal significance, continuity, individuality, expression/regulation
coherence, source fidelity and player agency separately. Strong expression,
restraint, silence and unexpected choices can each be coherent. Never reward
agreement, fewer gestures or a preferred label by default. Coordinate prose
repetition measurements with the existing narration-flow evaluator.

The current matrix uses a single reviewed response per authored context. It does
not establish generated long-term emotional progression, VN streaming, portrait
RGB or actual TTS behavior. Those need the corresponding integration paths and,
where necessary, separate live observation. Keep unrun cases and unrated outputs
explicit rather than interpreting technical success as psychological success.

## Historical initial live findings

These are results of the first smoke investigation, not a current release-wide
quality score or evidence that every later tool/workflow change was live-tested.

The first smoke investigation covered **four distinct fixture contexts**, with
repeated baseline/candidate attempts: **14 context executions and 56 recorded
model calls** (53 CHPM calls and three narrator calls). It did not complete the
24-context suite. Two executions reached an accepted narration; manual inspection
still found unsupported scene details. These counts describe diagnostics, not a
quality score or a statistically matched improvement.

With one optional agent round, the model selected the existing memory search and
belief-inspection tools. Search results retained their source IDs and historical
status in the proposal context. This demonstrates an actual tool step; it does
not introduce an MCP server or provide access to other observers' private data.

The main reliability obstacle was invalid proposals and their repair. Long field
values breached existing caps. When the original schema, required context and
complete rejected proposal did not fit together, the former repair regenerated
the object without seeing that proposal and could introduce different errors.

The candidate now attempts bounded **field edits** in that same single reserved
repair call for a parsed rejected cognitive draft whenever the complete edit
request fits, including when a full-object repair would also fit. This preserves
unedited fields rather than requiring the model to regenerate them. Other proposal
schemas retain their existing budget-triggered edit behavior.
It keeps required context, permits at most eight edits to enumerated JSON data
paths, reconstructs an uncommitted copy and rechecks the original schema and
semantic acceptance. It cannot execute commands, write files or publish partial
psychological state. If the complete object still does not fit, the existing
bounded regeneration fallback remains. Saved limits and request counts do not
increase.

Live field-edit repairs corrected the reported evidence error but exposed a
second, independent question-gate or intention-continuity error. Missing gate
feedback is now included when detectable before the first error is repaired.
The continuity failure remains a model-compliance limitation: the host still
requires a new intention when no prior delivered intention exists. An accepted
candidate execution needed no repair, so it is not evidence that field edits
improved acceptance. Generated multi-turn progression and psychological quality
remain unverified.
