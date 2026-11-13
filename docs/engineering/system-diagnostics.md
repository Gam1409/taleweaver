# System diagnostics

Administrators can enable **System Debug** under **System & Realm → System Diagnostics** and save the setting. It persists across backend restarts. It is disabled by default and independent of gameplay debug and raw LLM telemetry.

Diagnostics are written as JSON lines to `log/system-debug.jsonl` in the project root. Rotation retains at most five files: 5 MiB each in standard mode, 50 MiB each in detailed mode. Story strings retain their original language. Disabling diagnostics stops recording but retains existing files. The directory is ignored by Git and is not exposed through a download endpoint.

Events cover HTTP requests and disconnects, database queries and transactions, LLM calls and retries, embeddings, image generation, background jobs, and instrumented game pipeline stages. They include UTC timestamps, durations, outcomes, safe error types and stack locations, and correlation UUIDs where available. SQL is represented by its operation category, not its text. HTTP routes use registered route patterns, not user-provided paths or queries.

In standard mode, session messages, prompts, generated replies, credentials, request bodies, SQL parameters, and arbitrary exception messages are excluded. Existing application log records contribute severity and source locations rather than their free-form text. Enabling System Debug does not enable detailed content, legacy raw LLM telemetry or change console verbosity.

## Detailed logging

Enable **System Debug**, select **Detailed logging**, and save in the same settings
panel. Both flags are strict booleans and survive restart. Existing configuration
files and older API clients default to metadata-only logging. Disabling System
Debug also disables detailed logging.

Detailed events use the `detail.*` namespace in the same file. They include:

- Full model messages, JSON schemas, sampling parameters and raw response choices,
  including reasoning fields and tool calls, before narrative filtering or JSON
  parsing. Invalid JSON is still recorded. Retry metadata and available failed
  provider response bodies are recorded alongside the existing queue events.
- Stream batches, final usage/finish markers, partial output on disconnect or
  cancellation, and an explicit end record. The observer closes the source even
  when the consumer exits before requesting its first chunk.
- Every emitted turn event and progress update, player input, final state, engine
  operational messages, and instrumented preparation/application/validation
  boundaries. State changes include before/after values. NPC perception, prepared
  cognitive context, decisions, narration review/repair, scene/condition commits,
  item reconciliation and individual portrait-entry validation have explicit stages.
- Embedding input batches, configured model/timeouts, actual prefixed texts, HTTP
  response bodies and validated vectors. Memory retrieval includes selected
  documents and its audience/selection metadata. Image operations use the same
  provider lifecycle observer.
- SQL statement text and transaction/query metadata. Bound SQL values, HTTP
  authentication headers and account credential bodies are not captured.
- Caught memory-maintenance failures include their phase and safe stack locations,
  even when the worker handles the error and continues other maintenance phases.

Full story payloads are not clipped at the legacy 12,000-character telemetry limit.
Large payloads are split into `payload_json_part` records sharing `detail_group`,
`parts` and `payload_sha256`. Concatenate parts in numeric order and JSON-decode
the result. Rotation can eventually remove old records; collect the current file
and its rotated siblings after reproducing an issue.

Use `request_id`, `session_id`/`game_id`, `turn_id`, `call_id`, and engine step IDs
to follow interleaved requests. Engine turn boundaries reuse the transport's turn
ID. Operation start can precede queue admission: compare `inference.admitted`
and `inference.completed` to establish actual overlap. Queue records include the
endpoint fingerprint, request capacity and configured/legacy scheduling policy.
Turning detailed logging off invalidates active
capture tokens immediately: buffered old content is not written after re-enabling.
The mode does not send extra model requests or alter prompts, narration or game state.
It intentionally stores private story and NPC context locally; review files before
sharing them. Connection credential fields are excluded from selected wire data,
and recognizable credential assignments in operational engine messages are redacted.

The game displays a small session UUID while System Debug is enabled. The flag is refreshed with the session snapshot; an active turn may delay that refresh. Technical identifiers are not appended to ordinary player error messages.

## State rejection traces

Enable **System Debug**, select **State rejection traces** beside **Detailed
logging**, and save. The switches are independent: rejection traces work with
detailed logging off. The `state_failure_traces` setting is a strict boolean,
defaults to false for existing configurations and clients, and persists across
restarts. Disabling System Debug disables both content-capture switches.

An instrumented turn or background operation buffers the existing diagnostic
events. A dedicated `log/state-rejection-<generated UUID>.jsonl` file is published
only when a canonical validator rejects a proposed change, a required response
section is unconfirmed, or the operation fails or is interrupted. Confirmed empty
updates, successful no-ops, disabled features and repeated idempotent updates do
not produce rejection files merely because state stayed unchanged. This observer
does not classify refusal wording, bypass validation, or send additional model
requests.

Packets include the application/Python versions, session and turn identifiers
where available, full captured model requests and schemas, raw responses and
retries, engine boundaries and before/after state, explicit domain reason codes,
and available database/query/transaction metadata. Coverage includes item
placement and properties, physical conditions, scene facts and staging, movement,
emotion and cognition, progression/rules, scripts, clothing, Debug recovery and
failed NPC-journal/RAG maintenance. Deferred background work remains a normal
queue outcome rather than a rejected state change.
Partial acceptance retains both the accepted state and rejected proposals.
Foreground Debug commands stay within their caller's turn packet; explicitly
scheduled background jobs have independent packets. A trace end marker means
observation ended, not that a transaction committed. Database COMMIT events record
commit attempts; use the operation result and persisted state to confirm success.

Large evidence uses the same multipart representation as detailed logging. Each
operation has a 50 MiB evidence budget. Whole events exceeding the remaining
budget are omitted with explicit byte counts and hashes; compact rejection
summaries have a separate bounded allowance so the cause remains visible. The
footer reports omitted evidence and summaries. Retention keeps at most five
packets and 250 MiB in total; older packets are removed as new ones are written.

Files use generated names, private temporary writes, atomic publication and 0600
permissions; generated paths are validated with `ensure_within_base_dir`.
Credentials and bound SQL parameters are excluded using the existing diagnostic
filters. Full local story content is intentionally retained in rejection packets;
review it before sharing. The directory remains ignored by Git and has no public
download endpoint. With detailed logging off, buffered full content is not copied
to `system-debug.jsonl`. Turning capture off immediately invalidates active
buffers, and re-enabling it does not revive them. Storage failures are reported in
the diagnostics panel without changing gameplay results.

If storage becomes unavailable, gameplay continues and the diagnostics settings report a storage error. Check disk space and directory permissions. This logging mechanism is intended for the application's single backend process; sharing one rotating log directory across multiple backend processes is unsupported.
