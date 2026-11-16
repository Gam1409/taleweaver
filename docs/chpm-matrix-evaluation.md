# Cast and history evaluation matrix

The new matrix complements the existing paired comparison and trajectory harnesses.
It contains **360 cases**: three worlds × eight situations × five cast sizes ×
three history lengths. Every NPC has all seven current personality fields set.
Six profiles vary values, trust, communication, conflict style and risk tolerance.

- Worlds: everyday, science fiction, fantasy.
- Situations: ordinary initiative, player pressure, fear, embarrassment, trust
  repair, competing priorities, useful clarification, non-graphic adult attraction.
- Cast sizes: 1, 3, 5, 10, 20.
- Histories: 0, 12 same-evening turns, 40 turns across game days and two scenes.

Prehistory is explicitly authored synthetic speech, **not forty generated turns**.
Each run exercises actual perception, scheduling, source ingestion, cognition,
narrator, review/repair and commit functions in an isolated in-memory host. It
does not exercise a full database-backed VN turn, image generation, every possible
world event or background cognition. Existing game-loop tests cover host integration.

## Plan first; no inference by default

```bash
poetry run python -m backend.engine.chpm.evaluation.matrix_cli plan --suite smoke
poetry run python -m backend.engine.chpm.evaluation.matrix_cli plan --suite full
poetry run python -m backend.engine.chpm.evaluation.matrix_cli plan --suite large --all-present
```

`smoke` is six short cases; `large` is 24 cases with twenty NPCs and forty-turn
histories. A plan lists its maximum logical calls including narration and repair.
Planning does not discover models or send requests.

After explicitly starting the model server, choose a small subset and an adequate
total quota. For example, this single case allows at most nine logical calls:

```bash
poetry run python -m backend.engine.chpm.evaluation.matrix_cli run \
  --case fantasy-conflict-n20-h40 \
  --endpoint https://YOUR-SERVER/v1 --model YOUR_MODEL \
  --run-id cast20-first --max-total-calls 9
```

Add `--all-present` and use quota 26 to test twenty simultaneous active characters.
The harness deliberately uses larger explicit request limits for that test.
Alternatively use `--user ACCOUNT` for configured roles. Existing router, URL
validation and shared inference admission remain in effect. No session settings
or game state are written. An insufficient quota fails before model discovery.
New run IDs are required; previous logs are not overwritten. Transport retries
remain outside the logical quota.

Artifacts under `log/chpm-evaluations/RUN_ID/` include the manifest, one incremental
JSONL result per case and a completion summary. A missing completion summary means
the run may be incomplete; missing cases are never counted as passed. Each result
records phase timing, roles, input/output characters, provider token usage when
available, raw responses, decisions and before/after cursor/state details. Logs
can contain private prompts if adapted to real data; keep them private.

## Memory and dense-action stress suite

`--suite stress` selects five additional fixtures: literal recall after forty turns,
a paraphrase without matching cue words, a recent correction superseding an old
fact, many actions in three turns, and brief speech surrounded by outward actions
and a private thought. These are authored histories, not generated trajectories.

```bash
poetry run python -m backend.engine.chpm.evaluation.matrix_cli plan --suite stress
poetry run python -m backend.engine.chpm.evaluation.matrix_cli run \
  --suite stress --case recall-exact-h40 \
  --endpoint https://YOUR-SERVER/v1 --model YOUR_MODEL \
  --run-id memory-first --max-total-calls 7
```

Results include the actual perception projection and the proposal's bounded
`context_audit`: evidence excerpts, recalled fragment aliases, retrieval counts
and context packing tier. Check which facts reached the model before interpreting
its answer. Current CHPM episodic retrieval is lexical; missing a paraphrase is a
known capability limit, not evidence that semantic retrieval works. The general
game RAG pipeline is separate and needs its own retrieval/integration tests.

A server's advertised context window does not change CHPM's configured character
budget. Large raw-model context tests must be labelled separately from a full
CHPM turn. Count input tokens with the actual server tokenizer, leave output room,
and preserve timeout failures rather than accepting incomplete responses.

## What to evaluate

Hard tests check identity preservation, no inactive-state mutation, exact evidence,
budget bounds, invalid JSON, failed review/repair and no commit on failed turns.
The matrix additionally counts exactly duplicated candidate intentions. Semantic
distinctness requires reading the alternatives; string uniqueness cannot prove it.

Rate psychological behavior separately: whether motives support the decision,
whether different personalities actually choose differently when appropriate,
whether cooperation is voluntary rather than automatic, whether a useful question
is grounded, and whether experience qualifies behavior without replacing identity.
Include failed outputs and uncertainty. Fluent dialogue is not a passing score.

Use the existing paired/trajectory harness for baseline comparisons and consecutive
generated turns. The new matrix isolates cast/history dimensions; it is not a
controlled causal study and does not prove accurate human psychology.

Automated tests use mock models only. Live results are model- and configuration-
specific; inspect their artifacts and behavioral ratings before treating the
pilot as validated. Technical completion alone does not validate NPC psychology.

Matrix v3 introduced complete-fragment perception, explicit source freshness, derived goal alignment and a shared proposal-repair reserve. Matrix v4 adds completion metadata, output-budget rejection and contextual motive guidance. Compare models using the same version and budgets; the previous v3 live results are a diagnostic baseline, not a controlled v4 comparison. Saved kernel/snapshot schemas are unchanged by these evaluation and transport diagnostics.

## Matched personality contexts and output limits

`--suite continuity` plans fifteen fixtures: three fully specified profiles, each
with routine, familiar, breach, urgent and pressure variants. Authored identity and
goal are constant within each profile. These are counterfactual one-turn runs with
authored reported history, not longitudinal generated personality trajectories.
Neither agreement nor refusal is an expected golden action. See the
[final validation rubric](chpm-final-validation.md) for tie handling and manual review.

`--output-tokens 4096` explicitly changes the cognitive limit and temporary endpoint
role limits. It is recorded in the manifest; each call records its actual cap.
The default budgets remain unchanged. With `--user`, saved model-role caps still
apply, so inspect the effective call limit. Increasing tokens can exceed a proxy's
deadline even with a larger client timeout. An output-budget rejection does not
spend another identical retry. Incomplete transport calls stop the batch until
the operator verifies remote completion.
