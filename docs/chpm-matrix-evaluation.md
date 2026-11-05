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
total quota. For example, this single case allows at most eight logical calls:

```bash
poetry run python -m backend.engine.chpm.evaluation.matrix_cli run \
  --case fantasy-conflict-n20-h40 \
  --endpoint https://YOUR-SERVER/v1 --model YOUR_MODEL \
  --run-id cast20-first --max-total-calls 8
```

Add `--all-present` and use quota 25 to test twenty simultaneous active characters.
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

Automated tests use mock models only. A live run of this new matrix is still pending.
