# Frontend request and stream contracts

Application API requests use `services/http.ts` for URL construction, credentials,
authentication headers and a single unauthorized event. Raw fetch remains only
inside that transport and for external audio media, which is not an API request.

Finite requests include response-body consumption in their deadline and release
parent abort listeners after completion. The helper preserves response status,
headers and fetch metadata. Ordinary reads use 15 seconds; ordinary editor writes
allow 60 seconds. Long model-backed actions, image uploads and streamed turns
explicitly use `timeoutMs: null`, retaining the native response stream and their
server/caller deadline. NPC read controllers keep their existing whole-operation
timer and navigation cancellation. Do not apply a short browser timeout to a
generation request whose completion may be uncertain.

Chat and play-agent consume the same SSE parser. It supports LF, CRLF and CR,
Unicode characters split across network chunks, multiple data lines, heartbeat
comments, cancellation and obsolete-session guards. Malformed JSON is an error;
an unterminated event at EOF is not a confirmed final receipt. Existing turn
reconciliation still verifies saved history rather than repeating the action.

Gameplay's notification composable is a facade over the editor's notification
service. One application-level component renders notifications. IDs, dismissal
and timer cleanup share one store; existing five/eight-second durations remain
appropriate to each caller.
