# NPC analysis performance

Session **NPC Personality** settings expose **Concurrent NPC analyses** and
**Last NPC analysis timings**. Existing sessions default to one analysis at a time.
Save a value of two to try overlapping independent NPC requests; the maximum is four.
The character roster, active cast, context, output limits and request budget stay
unchanged. Changing concurrency does not reset the confirmed minds or replay history.

## Measuring a turn

The completed analysis retains at most 25 request records, matching the existing
logical request cap. The owner can inspect them without another inference call.
Old saves have no timing records; missing measurements display **Unavailable**.

- **NPC preparation wall time** covers preparation through the completed decisions,
  including shared perception, host reads and optional agent lookups. It excludes
  subsequent narration and its review. It is recorded on analysis failures as well.
- **Total** is the observed logical request duration, including admission and parsing
  performed by the router. Provider retries remain inside that logical request.
- **Host queue** is waiting in TaleWeaver's inference admission queue. It does not
  measure the provider's internal queue. A measured zero differs from unavailable data.
- **First token** is time from dispatch until the first visible text chunk. It includes
  network delay, server waiting, input processing and preceding provider attempts.
  Non-streamed CHPM calls cannot report it; no extra streaming request is sent.
- **Input processing**, **Server generation** and **Model load** use provider-reported
  durations when present. Ollama-style nanosecond fields are converted to milliseconds.
  Proxies can omit these values. Total latency is never presented as pure input processing.
- **Cached input tokens** uses the provider's reported cache count when supplied.

The content-free `llm.completed`, `llm.failed` and `llm.cancelled` system debug events
carry the same measurements for other roles, including narrator streams.
`stream_generation_ms` is observed time after the first visible text chunk; it can
include consumer backpressure and differs from provider-reported generation time.
Prompts, responses, endpoints and credentials are not stored in timing records.
Raw LLM telemetry can remain disabled.

Compare ordinary turns with similar active casts and response sizes at one and two
concurrent analyses. Use preparation wall time rather than summing overlapping request
durations. These measurements do not establish a quality or speed benchmark.

## Parallel execution boundary

Source checking and database reads run sequentially against the same leased turn.
The read transaction is released before independent cognition starts. Each job has
its own observer inputs and psychological projection. Results are merged in actor-ID
order only after all jobs succeed. The existing shared narration review and completed
turn transaction still govern psychological persistence and publication.

The same global request counter and single shared proposal retry apply. Outstanding
normal requests retain their reserve even when other NPCs finish earlier. Concurrent
failures do not gain extra retries. Already-started requests may finish on failure,
so a failed parallel turn can spend more of the existing budget than a sequential
turn that would have stopped earlier. It never increases the configured cap.
Cancellation drains child tasks; transport rules still fence uncertain work.

Local/custom-server admission remains serialized when configured that way. Parallel
NPC jobs do not bypass this queue or its uncertain-request protection. A provider
that serializes work may show no speed gain. Sequential mode remains available for
baseline measurements and servers with one effective inference slot.

Settings and timing fields are additive with safe defaults; the persisted CHPM
schema version remains six. No live paid-model benchmark was run for this change.
