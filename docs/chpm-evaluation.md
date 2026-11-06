# CHPM dialogue comparison and stress testing

This is an explicit operator tool. It is not called by the game loop and does not
change the default CHPM setting or existing adventure/session data. Planning makes
no model request. Running uses synthetic cases and the normal inference router,
including its endpoint validation, admission queue and timeout handling.

The suite has **41 cases**:

- 20 bilingual short cases: continuation, missing information, independent goals,
  emotional aftermath, private thoughts, contrasting voice, forged state,
  changed plans, private-only input and conflicting requests.
- Two bilingual cases containing 40 authored player/NPC turns (80 messages),
  revised plans, changed locations, growing rapport and an early open promise.
- Six different complete personality profiles in the same short and 40-turn
  situations (12 cases); the circumstances and goal are held constant.
- Seven states of one fully authored adult character, Dina Volkova: calm, fear,
  embarrassment, a trauma reminder, non-graphic adult attraction/arousal, an
  unsupported demand to rewrite her personality, and justified protective anger.

Dina has every canonical personality field filled: temperament, sociability,
speech, trust, value, conflict and risk. All seven scenarios retain the same card,
profile and goal. Fear/arousal/trauma are authored circumstances here, not newly
implemented numeric psychological states. The review rubric is withheld from all
model requests.

## What the comparison measures

Both arms receive the same narrator instructions, character, voice example,
public scene, witnessed history and player input. The baseline is an authored,
context-rich dialogue prompt, **not an empty prompt**. The CHPM arm additionally
uses production perception, observer context, proposal/selection, dialogue
contract, semantic review, and the existing single repair policy. Production
turns and evaluations share the cognitive selection boundary.

This is an **isolated dialogue comparison**, not the complete standard TaleWeaver
pipeline, a Concordia performance test, or a full session simulation. It does not
run standard social planners, RAG retrieval, world mutations or replay/DB commits.
Authored fixture history is supplied directly; source checks and transactional
rollback are tested separately by the real VN integration tests. The 40-turn histories are authored fixtures, not 40 sequential live
generations. Each test generates one next reply. Long-term individuality or
relationship development cannot be established from this design. There is no automatic literary judge and no calibrated psychology score.

Every repetition starts fresh. Baseline-first and CHPM-first execution alternate
to reduce systematic ordering effects. Repetitions are independent model samples;
the tool does not assert provider seed determinism. A/B presentation is separately
shuffled and bound to the saved response hashes. Model identity, arm identity,
latency, trace and token counts are excluded from the blind review document.

## Commands

Run from the repository root, with the normal application dependencies installed.

```bash
# No DB, credentials or GPU required; inspect cases and maximum logical calls.
poetry run python -m backend.engine.chpm.evaluation.cli plan
poetry run python -m backend.engine.chpm.evaluation.cli plan --case continue-ru --repeats 3

# Explicit live test using an existing account's configured roles.
poetry run python -m backend.engine.chpm.evaluation.cli run --user admin --case continue-ru --run-id chpm-first-test

# Temporary unauthenticated OpenAI-compatible endpoint; no settings are saved.
poetry run python -m backend.engine.chpm.evaluation.cli run --endpoint https://your-server.example/v1 --model your-model-id --case continue-ru --run-id chpm-endpoint-test

# Full 41-case suite; start with one repetition before increasing the cost.
poetry run python -m backend.engine.chpm.evaluation.cli run --user admin --run-id chpm-stress

# After a human fills ratings.jsonl, recompute the report without inference.
poetry run python -m backend.engine.chpm.evaluation.cli report --run-id chpm-first-test
```

For a temporary endpoint, `--model` can be omitted only when `/models` advertises
exactly one model. Authenticated endpoints should use the existing account/provider
vault with `--user`; there is no command-line API-key argument. Roles Small and
Complex use the same temporary model when `--endpoint` is supplied. With `--user`,
the account's configured role routing is preserved. Optional `--role small` selects
the CHPM cognitive role; narration and repair remain Complex.

`--case` is repeatable; omitted means all cases. `--repeats` accepts 1–20 (default
1). `--calls` bounds logical CHPM requests per arm (3–8, default 6). The initial
narrator request is additional; baseline makes one request. `plan` reports a
conservative hard maximum. A successful one-NPC CHPM arm normally uses four total
requests, or six with a repair and second review. The default full suite therefore
normally uses 205 requests without repairs, with a conservative configured ceiling
of 328. Router/provider retries may add physical attempts and cost.

`--timeout` is 10–600 seconds per logical call (default 120), bounded by the model
configuration's timeout. Narration output is capped at 1,200 tokens in both arms;
CHPM decision/review limits use the existing Settings defaults and repair retains
its 4,096-token cap. Thinking is disabled by this evaluation port. No inference
queue entry is automatically cleared after a timeout; normal queue recovery rules
remain in effect. The process does not bypass the application's URL policy.

## Artifacts and human review

Files are stored under `log/chpm-evaluations/<run-id>/`, outside served game assets
and ignored by Git. Paths use the shared path-security helper. An existing run
cannot be overwritten. JSON input artifacts are capped at 32 MiB.

- `manifest.json`: exact case inputs, suite version, limits, source fingerprint and
  the private blind-assignment seed. Do not show it to the blind reviewer.
- `results.jsonl`: completed arm records, final replies or failures, decisions,
  validation verdicts, per-phase counts and durations. Failed replies are not
  published as successful answers. Returned model text is captured privately for
  diagnosis; text beyond 64,000 characters is explicitly marked truncated in this
  diagnostic field, while validation still processes the actual returned text.
- `review.md`: A/B replies and the authored case criteria, without arm metadata.
- `ratings.jsonl`: initially null scores. Review **voice**, **grounded initiative**,
  **question relevance**, and **continuity** on a 0–4 scale (higher is better).
  Choose A/B/tie/unrateable and explain the preference. A necessary question or an
  in-character refusal is not automatically a defect. Unknown stays null.
- `summary.md`: failures, logical calls, repairs, provider usage coverage, final-text
  latency p50/p95 and paired human ratings when available. Empty/incomplete ratings
  produce a pending quality verdict, never zero scores or an automatic win.

Do not open raw results or the manifest before a blind review. A reviewer may still
infer the arm from its style: blinding removes labels, not every possible clue.
Only complete, successful pairs with all dimensions and a preference enter quality
averages. Failed attempts remain in operational failure/call metrics. Duplicate or
unknown ratings, invalid scores, and hashes from changed answers are rejected.
Interrupted runs disclose missing arms; they are not counted as successful or
silently inserted as zero-cost responses. Rerun using a new run ID.

Usage is captured from actual provider response fields even when file telemetry
is disabled. Missing or malformed counts remain unknown. Provider-reported totals
cover only calls with both counts; they are not billing totals because retries or
failed requests can be unreported. Characters are recorded separately. Latency is
end-to-end time to a final accepted text, not streaming time-to-first-token. The
p50/p95 calculation uses successful attempts and nearest rank; small samples and
selective human rating do not establish statistical significance.

## JSON and transaction stress tests

The parser accepts one JSON object, optionally surrounded by one complete Markdown
code fence. It does not repair truncated JSON, reinterpret wrong IDs, merge multiple
objects, accept duplicate keys, allow nonstandard NaN/Infinity, or coerce strict
booleans. Proposal responses use an object keyed by unique action kinds and normalize to
the existing stored candidate list. Duplicate keys fail; they are never merged.
Review responses cite passage IDs instead of recreating quotations. The host
resolves IDs to bounded exact narration substrings, then applies existing actor,
hearing and agenda checks. Response schemas enumerate allowed actor/speaker and
passage IDs. Unknown IDs and extra quote fields fail; a missing reference is
allowed only for a silent DEFER. Model-facing format changes do not migrate stored
kernel state or loosen exact-source checks.

These checks do not prove semantic correctness. A reviewer can mistakenly accept
an invented promise or attribute narration to an actor. Passage IDs prevent quote
rewriting, not incorrect interpretation. Structural acceptance must be reported
separately from faithful intentions, world facts and quality of voice.

The regression suite corrupts output at perception, proposal and review boundaries
inside real recoverable VN turns. It checks that no unchecked text is published,
no assistant reply is saved, and existing observer memory/agenda survives rollback.
Other tests cover source edits, retries, budget exhaustion, cancellation, actor
isolation, settings transitions, private trace access and snapshot restoration.
These establish program invariants, not the literary quality of a live model.

## Deliberately wrong narrator output

After a successful CHPM arm, a separate explicit probe can reuse its decision and
inject a conflicting promise and invented world action into the reviewer.
`--violation takeover` replaces the reply with a blatant reversal; `promise`,
`completed_action` and `shared_history` append one unauthorized statement to the
previously accepted reply. These test omissions that a coarse overall-stance check
might miss. It
records the initial verdict, whether the injected text would be accepted, the
single repair attempt and final result. It does not publish or mutate game data.

```bash
poetry run python -m backend.engine.chpm.evaluation.cli probe --user admin --source-run chpm-first-test --case continue-ru --run-id chpm-control-test
```

`--endpoint`/`--model` also work. The probe reuses the source run's CHPM settings;
`--timeout` applies to its requests. It writes `control.json` and `control.md`.
One caught counterexample does not establish universal control. A false acceptance
must remain visible, not be relabeled a successful test of the reviewer.
