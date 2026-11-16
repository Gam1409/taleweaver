# Frontend request and stream contracts

Shared application transport lives in
[`services/http.ts`](../../frontend/src/services/http.ts): URL construction,
credentials, authentication headers, cancellation and the unauthorized event.
API wrappers reuse this transport and can set their own deadlines. External media
requests are a separate concern.

## Request deadlines

Finite requests include response-body consumption in their deadline and release
parent abort listeners after completion. Response status, headers and fetch
metadata are preserved. The default belongs to the wrapper actually used:

| Call path | Current deadline |
| --- | --- |
| `apiFetch` without an override | 15 seconds. |
| `useApi.ts` request wrapper | 20 seconds unless its call supplies another numeric value. |
| Authenticated-user refresh (`store/auth.ts`, `/auth/me`) | 12 seconds. |
| Session / NPC settings wrappers | Commonly 15 seconds; specific operations can override it. |
| Ordinary editor writes | Commonly 60 seconds in their service wrapper. |
| Community catalog fetch/refresh | 30 seconds. |
| Community catalog install | 10 minutes, including bounded file transfer/import. |
| Streamed turns and selected long model/image operations | Explicit `timeoutMs: null`; caller cancellation and server/provider deadlines still apply. |

These are client request deadlines, not model context or output-token budgets.
Check the service call instead of applying one blanket read/write timeout.
NPC read controllers also retain whole-operation timers and navigation cancellation.
An uncertain write outcome must be reconciled from saved state rather than
retried automatically as a new action.

## Streaming and request ownership

Chat and Play-Agent consume the shared SSE parser. It handles LF, CRLF and CR,
Unicode split across network chunks, multiple data lines, heartbeat comments,
cancellation and obsolete-session guards. Malformed JSON is an error; an
unterminated event at EOF is not a confirmed final receipt. Turn reconciliation
checks saved history instead of repeating an uncertain player action.

Gameplay notifications use a facade over the shared editor notification store.
The application-level renderer, IDs, dismissal and timer cleanup stay with that
owner. A notification is not evidence of a committed gameplay mutation.
