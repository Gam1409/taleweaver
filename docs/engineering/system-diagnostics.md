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

If storage becomes unavailable, gameplay continues and the diagnostics settings report a storage error. Check disk space and directory permissions. This logging mechanism is intended for the application's single backend process; sharing one rotating log directory across multiple backend processes is unsupported.
