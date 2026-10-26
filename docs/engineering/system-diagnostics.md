# System diagnostics

Administrators can enable **System Debug** under **System & Realm → System Diagnostics** and save the setting. It persists across backend restarts. It is disabled by default and independent of gameplay debug and raw LLM telemetry.

Diagnostics are written as English JSON lines to `log/system-debug.jsonl` in the project root. Rotation retains at most five files of approximately 5 MiB each. Disabling diagnostics stops recording but retains existing files. The directory is ignored by Git and is not exposed through a download endpoint.

Events cover HTTP requests and disconnects, database queries and transactions, LLM calls and retries, embeddings, image generation, background jobs, and instrumented game pipeline stages. They include UTC timestamps, durations, outcomes, safe error types and stack locations, and correlation UUIDs where available. SQL is represented by its operation category, not its text. HTTP routes use registered route patterns, not user-provided paths or queries.

Session messages, prompts, generated replies, credentials, request bodies, SQL parameters, and arbitrary exception messages are excluded. Existing application log records contribute severity and source locations rather than their free-form text. This intentionally limits what can be diagnosed from a log alone. Enabling System Debug does not enable raw LLM telemetry or change console verbosity.

The game displays a small session UUID while System Debug is enabled. The flag is refreshed with the session snapshot; an active turn may delay that refresh. Technical identifiers are not appended to ordinary player error messages.

If storage becomes unavailable, gameplay continues and the diagnostics settings report a storage error. Check disk space and directory permissions. This logging mechanism is intended for the application's single backend process; sharing one rotating log directory across multiple backend processes is unsupported.
