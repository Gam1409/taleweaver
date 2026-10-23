# Refreshing action ideas

The Ideas popup sends a dedicated `POST /api/adventures/{session_id}/suggestions`.
It does not send a chat turn, advance game time, or interrupt narration. Typed
`/shuffle`, `/suggest`, and `/suggestions` commands use the same frontend request.
The HTTP `/shuffle` alias remains available.

The refresh indicator follows the actual request. Repeated clicks are blocked
while it is running. The previous list remains available. The popup distinguishes
updated ideas, an unchanged model response, invalid output, connection errors, and
timeouts. Starting a turn, changing language, or leaving the session discards a
pending client response. Refresh is unavailable while narration or the play agent
is running.

Manual refresh uses the configured Small / Utility LLM and the saved session
language. Previous suggestions are included as data so the model can offer other
valid actions without inventing entities or puzzle solutions. The server allows
90 seconds; the browser allows 95 seconds for the response to arrive.

Manual failures return an error without replacing saved ideas with generic
fallbacks. Automatic suggestions during normal turns retain their existing
localized fallback behavior. A result for an outdated scene, last narration, or
language is rejected. Successful saves merge ideas into the latest exit state.
Both reading and refreshing suggestions check session ownership.

## Verification

- Mocked backend tests cover model role, session language, persistence, unchanged
  game time/history, malformed output, provider errors, timeout cancellation,
  concurrent scene/language/exit changes, ownership, and legacy Cyrillic IDs.
- Frontend tests exercise the real request composable with deferred responses,
  duplicate clicks, identical output, errors, timeout, and discarded late results.
- Chromium checks exercised the actual action bar and game socket with mocked
  HTTP responses, including typed commands, Russian text, and mobile layout.
- The game-loop and content-language regression suites passed. The production
  frontend build passed. Type checking still has the same 129 distinct pre-existing
  diagnostics after normalizing source line numbers; no new diagnostics were added.

No live model or image server was used for these checks.

## LiteLLM cancellation warning

`coroutine 'BaseLLMHTTPHandler.async_completion' was never awaited` is separate
from Alembic's informational `Will assume non-transactional DDL` message.
TaleWeaver awaits its asynchronous completion calls. A cancellation race was
reproduced in the installed LiteLLM 1.103.1 dispatcher with a mocked provider and
no network: cancellation during `run_in_executor` can leave the returned provider
coroutine unconsumed. This does not prove the cause of any particular user log.

The Ideas change avoids using a refresh click to cancel an active chat request;
it does not patch or suppress the dependency warning. To capture the coroutine's
creation traceback on Windows, stop the app and run this from the repository root
in PowerShell:

```powershell
$env:PYTHONTRACEMALLOC = '10'
.\run.ps1
```

Reproduce the warning and retain the complete warning and allocation traceback.
After stopping the app, disable tracing with:

```powershell
Remove-Item Env:PYTHONTRACEMALLOC
```

The standard-library path may point to Miniconda even when a virtual environment
is active. Check the runner's `Backend Python:` line before concluding that the
wrong interpreter is being used.
