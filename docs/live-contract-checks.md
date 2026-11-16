# Live state, tools, emotion and initiative checks

Status: prepared evaluation harness. Offline verification of the harness is not
evidence of model quality. No saved game, account credentials or previous provider
address is used. Supply a current endpoint explicitly for each run.

## Scope and ownership

The suite drives the real VN `GameTurnManager` in synthetic in-memory sessions.
Production roles, prompt packing, CHPM staged/integrated decisions, native/JSON
tool loops, review, reconciliation and accepted-turn persistence remain active.
The harness observes the existing admitted LLM gateway and tool dispatcher; it
does not rewrite model answers or add a second state reconciler.

The pytest fixtures disable world/media generation, speech generation and
background memory maintenance. Those services and real vector-index performance
are outside this suite. Notebook reads and observer state tools use their real
implementations. Ordinary test discovery does not collect `tests/live_contracts.py`;
explicitly invoking it without the CLI gate skips it.

| Group | Cases | What is exercised |
| --- | ---: | --- |
| `state` | 6 | Explicit/literary item placement and sleeve displacement, cleaning without erasing an injury, movement along an existing open route |
| `tools` | 6 | Staged/integrated × JSON/native, a later-turn notebook read, missing-path feedback, another NPC's private notebook isolation |
| `emotions` | 8 | Four matched situations with Personality off/live: overt conflict, concealed concern, mixed success/threat, reconsideration after new evidence |
| `autonomy` | 5 | Opportunities to move, take a lantern, change wet clothing, initiate conversation and respond to conflict without a player command |

One complete repetition has **25 cases and up to 43 turns**. A failed first turn
ends that case; its second turn is not counted as tested. Repeat a selection to
observe variability. One run is a smoke result, not a reliability estimate.

## Preparation without inference

Use the locked dependency environment. Preflight checks LanceDB and PyArrow too,
so an absent test dependency is reported before any paid request.

```bash
poetry install
poetry run python scripts/run_live_checks.py preflight
poetry run python scripts/run_live_checks.py plan
poetry run python scripts/run_live_checks.py plan --group emotions --repetitions 3
```

Planning requires neither credentials nor a provider URL. The planning allowance
is a conservative gateway ceiling, not measured token use, billing or predicted
latency. Actual model usage is recorded when the provider supplies it.

## Explicit run

Set `TALEWEAVER_EVAL_ENDPOINT` locally to the current API address. A root URL,
`/v1`, or `/v1/chat/completions` is normalized to the same API base. Credentials,
if required, belong in `TALEWEAVER_LIVE_API_KEY`, not URL parameters or arguments.
The API URL must satisfy the application's normal provider network policy.

Start with a narrow selection, then run the whole matrix with a fresh run ID:

```bash
poetry run python scripts/run_live_checks.py run \
  --endpoint "$TALEWEAVER_EVAL_ENDPOINT" \
  --case state-place-explicit --case tools-integrated-json \
  --run-id contracts-smoke-01 --max-calls 105

poetry run python scripts/run_live_checks.py run \
  --endpoint "$TALEWEAVER_EVAL_ENDPOINT" \
  --run-id contracts-full-01 --max-calls 1505
```

If `/v1/models` advertises other than exactly one model, supply `--model` explicitly.
All foreground text roles use that same model in a temporary test account.
`--output-tokens` defaults to 4096; `--timeout` defaults to 180 seconds per provider
request. CHPM retains its production three tool-round bound and 25-call turn cap.
The separate run quota counts every gateway invocation, including structured,
streamed and native tool requests. Model discovery is not an inference request.

Sampling and internal prompts remain production defaults. Compare matched cases
with the same model/server configuration, limits and revision. A model that cannot
speak native tools may fail those cases; the harness does not silently change
their protocol to JSON.

Each run owns a fresh database and one shared inference registry across its cases.
An uncertain transport, incomplete stream, unexpected provider or exhausted quota
prevents further dispatch. The registry remains in the private run folder; do not
reset an uncertain remote job by immediately starting another run. Complete
schema/quality failures are distinct from transport uncertainty.

## Evidence and independent review

Artifacts live under ignored `log/live-contracts/<run-id>/`:

- `manifest.json`: selected synthetic cases and repetitions.
- `calls.jsonl`: allowlisted requests, responses, durations, client first-chunk
  timing and provider usage when available. Headers, keys and API addresses are
  excluded. First chunk is not a server-side first-token measurement.
- `results.jsonl`: current generated reply, public portrait cues, actual tool
  receipts, prior prose, before/after canonical state and notebook data.
- `review.md`: context/prose-only samples with opaque identifiers, without workflow,
  model self-labels, tool output or portrait emotion labels.
- `ratings.jsonl`: independently completed annotations bound to exact result hashes.
- `summary.json`: technical totals and descriptive reviewed-sample statistics.

Results, calls, ratings and review files are individually bounded at 32 MiB.
These are private diagnostics; do not attach them automatically to GitHub.
Paths use the central `ensure_within_base_dir` and `sanitize_path_component` helpers.

Read `review.md` before exposing the model's internal labels. Fill independent
`inferred_internal`, `narrated` and `dialogue` multi-label annotations with exact
evidence quotes. `null` means unknown; `[]` is an actual judgment of no affect.
After the blind annotation, inspect tool receipts and before/after state to
complete action consistency and player-agency judgments. Mark a sample `reviewed`
only when all required judgments are complete. Rebuild the report:

```bash
poetry run python scripts/run_live_checks.py review --run-id contracts-full-01
```

Keep labels consistent, such as `anger`, `fear`, `sadness`, `joy`, `shame`,
`interest` and `arousal`, preserving finer distinctions in notes. The report
separates raw declared decision affect from newly accepted canonical affect.
Missing/unparseable declarations remain unknown. Exact-set agreement with an
independent interpretation is descriptive and sensitive to label granularity;
it is not a pass threshold or calibrated psychological accuracy. Unreviewed
samples are never scored as correct. Inspect portrait names/RGB against the
visible expression, rather than requiring a hidden feeling to appear on the face.

The [reviewed emotion research](engineering/emotional-progression-research.md)
supplies contextual criteria: experience versus expression, regulation, mixed
feelings, uncertainty and relationship continuity. It does not supply a universal
percentage of anger, joy or initiative that a fictional scene must match.
Prose, everyday conversation and experimental psychology use different samples
and annotation schemes. No population-frequency comparison is claimed without a
separately chosen, licensed and annotated reference corpus. These authored scenes
and their repeats describe only this engine/model experiment.

## Initiative and consequences

Follow **motive → decision → narration → accepted state → next turn**. Inspect the
selected candidate and motives, rather than an isolated sentence claiming
independence. Permission-seeking is a defect when it outsources the NPC's own next
step; a question needed to learn an external fact or the player's intention is valid.

Agreement, refusal, counteroffers, waiting and a believable mistake can all fit a
character. The conflict case allows grounded fictional aggression, but neither an
attack nor a refusal is a required answer. The NPC chooses its own actions; the
player retains voluntary choices and reactions. An attempt is not automatically
successful. If narration says an item moved, inspect identity, ownership and
placement in the saved state and again on the next turn.

A missing notebook write/read is **not exercised**, rather than evidence of
memory. Check that a later turn starts with the same committed document and that
reading it has a real tool receipt. Note content remains freely organized,
self-authored and subjective; it is never promoted to world evidence.

## Existing mechanisms and follow-up research

The engine already has mechanisms proposed by many agent-loop designs: CHPM
`selected`/`previous_intention`, source-grounded motives, an agenda, observer-scoped
memory/notebooks, validation, canonical reconciliation and a separate Living World
clock/event owner. Reuse those owners before adding another goal database,
scheduler or action executor.

This initial suite measures choices during player-triggered VN turns. It does
**not** demonstrate continuous off-screen life or automatic starts while the player
is idle. Those need separate Living World event/timer tests: blocked-route
adaptation, stopping after goal completion, interruption/resumption, knowledge
isolation and conflicts over one item. A shared LLM can serve separate NPC contexts;
no weight update is required to test these mechanisms. Long-term stability and
quality remain empirical questions.

Research proposals for always-on loops, need decay or planners are not implementation
instructions. Compare them with existing owners and measured failures first. The
supplied autonomy review is useful as a mechanism map; its external paper-specific
results have not all been independently rechecked in this preparation change.
