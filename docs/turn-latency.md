# Understanding turn latency

`Checking progression...` covers the continuity model request, including its
admission wait and any router retry. Once it returns, `Applying progression...`
covers host validation and resolution; a scene transition or a new local place
may require another model request. Preparation of narration and NPC responses has
separate status messages. `Generating narrative...` starts at the narration call.
In live NPC Personality mode the reply still needs review before publication.

The progression input contains the current state and only the latest assistant
narration (bounded to 8,000 characters in VN mode). Older dialogue is not appended
to this request. Inventories, wardrobe, notes and the list of locations can change
its size even when the number of recent messages is constant. Causal continuity is
a bounded current view for NPC decisions/narration; it does not append its full
graph or all source messages to progression.

## Measurements

With system diagnostics enabled, filter `gm.turn.pipeline.context` and
`gm.turn.pipeline.pass` by `phase=chat_progression` and session/game ID. The context
event records `chars`: system text, user text and serialized response schema size
in characters, **not tokens**. The pass event records wall time around the actual
model call, including failed and cancelled calls, separately from host resolution.
Correlated `llm.started/completed/failed/cancelled` events identify individual
requests and retries; the inference queue exposes admission state. These events
do not record story text or credentials. Raw prompt telemetry is separate and
contains sensitive story detail.

KoboldCpp's `Processed` and `Generated` timings separate reading the prompt from
generating output. A 131k context setting is a ceiling, not the number of tokens
used by each request. A generation allowance such as `12288` is also a ceiling,
not evidence that the server generated that many tokens. Reasoning, when emitted
by a model, contributes to generation time even if it is hidden in the UI.

At 18 tokens/second, 900 generated tokens alone take about 50 seconds. Repeated
technical calls and narration share that cost when they use the same single-slot
server. Prefix cache reuse can be limited when those requests alternate distinct
prompts. A slow first call alone does not prove a memory leak or growing history.

## Improving latency without losing continuity

Use the per-role provider/endpoint settings to put the `small` technical role on a
fast structured-output model and keep the literary model for narration. Compare
correctness as well as time before changing the model or disabling its reasoning.
Lower output ceilings only after observing actual output lengths: cutting off JSON
can trigger repair or a failed turn. Increasing context size does not speed up
generation. Do not clear an uncertain inference lease while the remote request may
still be running.

The host batches newly observed excerpts into one source-ledger validation and
hashes each source message once per reconciliation. Every source binding and exact
quote is still checked. There is no cross-turn hash cache, skipped replay
validation, discarded evidence or automatic reduction of the user's context.
