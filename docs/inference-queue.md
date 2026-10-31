# Experimental shared inference queue

This is the inference prerequisite for Living World deliberation. It does not add
NPC decisions or enable Concordia by itself. The opt-in [Living World](living-world-usage.md)
decision layer uses this queue as a prerequisite. The default is **off** for compatibility.

## Enable

Set `INFERENCE_SERIALIZATION_ENABLED=true` in the backend `.env` and restart the
normal **single-worker** backend. Open **Administration → Intelligence → Inference
queue · Experimental** to inspect outstanding work. The card also appears when
admission is disabled so unresolved work can still be inspected.

Guarded paths:

- GameMasterLLM Ollama and administrator-managed OpenAI-compatible requests, both
  synchronous and asynchronous, including streamed narration and structured tasks.
- Configured memory embedding HTTP requests, so Ollama embeddings cannot run beside
  narration on the same server.
- Background maintenance calls inherit background priority from the existing idle
  scheduler. Waiting foreground requests take priority; running remote work is not
  forcibly preempted. Background admission rechecks that the game is still idle.

Hosted providers using their normal cloud routing retain their previous behavior.
ComfyUI/image inference is not coordinated by this text/embedding queue.

Endpoints are grouped by scheme, hostname and effective port, independent of model,
role, account, and `/api` or `/v1` path. Loopback aliases share a group. Two different
DNS aliases, proxies or ports reaching the same GPU are **not** automatically known
as the same server: configure a consistent base URL. Separate origins can run
concurrently. No DNS lookup or request content is used for identity.

Queue waiting consumes the configured LLM request allowance; the remaining timeout
is passed to the provider. No fixed 90-second timer is introduced. Streaming retains
its existing provider/silence timeout behavior. Queue timeout before submission does
not mark the server as uncertain. Synchronous code cannot block the event loop while
waiting for a busy endpoint; it must use the asynchronous API or a worker thread.

## Timeout, cancellation and restart

Before dispatch, the queue durably records the request token. A complete non-stream
response or a stream completion marker permits release. Closing a stream early,
EOF without a completion marker, a connection failure, or an ambiguous timeout leaves
an **UNCERTAIN** reservation. Explicit request rejections such as HTTP 400/401 release
it; 5xx exceptions remain conservative. A truncated stream without a completion
marker raises an error rather than silently looking like a completed response.

Automatic connection/timeout retries, including SDK retries, are disabled on guarded
completion paths. Retrying the game, changing the model role, or restarting TaleWeaver
cannot bypass the unresolved reservation. New work on that origin fails before it is
sent. Cancellation of a waiting caller leaves the running request untouched. Late
non-stream results from a cancellation-resistant transport are discarded, not delivered
for application to the world.

Recovery requires an administrator:

1. Check the remote inference server and stop its outstanding generation, or restart
   that server. A successful `/health` response does not prove its GPU queue is empty.
2. Refresh the Inference queue card. Select **I verified that remote generation has
   stopped**, then **Clear stopped request** for the uncertain row.
3. Retry the original gameplay/background operation normally. Clearing does not rerun
   an operation, invent a decision, or apply a late response.

The control cannot clear a live local request. Its request token must still match;
replayed acknowledgements return 409. It does not invoke a provider abort endpoint.
To identify a configured URL's fingerprint locally without contacting it:

```sh
poetry run python -c 'from backend.core.inference.registry import endpoint_key; print(endpoint_key("http://127.0.0.1:11434"))'
```

## Persistence and boundaries

The runtime journal is `${DATA_DIR}/inference-reservations.json`, written with file
flush/fsync and atomic replacement. It contains endpoint hashes, request UUIDs and
start timestamps only: no URLs, API keys, prompts, responses, NPC memories or private
thoughts. It is runtime coordination, separate from SQL world state and LanceDB.
The public `/data` mount denies this JSON file and its temporary replacement files;
only media extensions are served. Keep the journal in place to preserve recovery fences.
Keep DATA_DIR on persistent local storage, not an ephemeral remote GPU volume.
Unfinished records loaded after a restart become uncertain; corrupt or unwritable
storage fails closed before new remote submission. Do not delete the journal to
bypass recovery. Backups of world state do not rewind remote inference reservations.

This is **not a distributed inference scheduler**. Use one backend worker and one
backend process per journal. Other applications sending requests to the same GPU
are outside this queue. Disabling the flag intentionally restores the old unguarded
behavior; only do so after stopping unresolved remote work. The reservation itself
opens no SQL transaction and performs no world mutation. Recoverable gameplay turns
use separate durable checkpoints to release SQL writers during model waits; see
[review remediation](engineering/review-remediation-2026-10.md).

## Verification

```sh
poetry run pytest -q tests/test_inference_reservations.py tests/test_inference_integration.py
poetry run pytest -q tests/test_llm_router.py tests/test_llm_router_retry.py tests/test_custom_openai.py tests/test_stream_timeout.py tests/test_memory_scheduling.py tests/test_memory_rag_embeddings_store.py
poetry run mypy backend/core/inference backend/api/routes/inference_queue.py --follow-imports=silent
cd frontend
npm run build
```

Tests use fake transports and real admission, registry persistence and authenticated
API requests. They cover cross-role/cross-endpoint ordering, background priority,
embeddings vs narration, streaming lifetime, deadlines, cancellation, late results,
crash recovery, stale/admin-only acknowledgement, disk failure and the disabled path.
No live GPU or real-browser E2E test was performed.

Recorded checks for this step: the final Living World/replay/provider selection
passed 144 tests, and the diagnostics/admission selection passed 57 (these selections
overlap). The earlier router/retry/embedding selection passed 139 tests. Ruff and
format checks passed for all 13 modified/new Python files, mypy passed for the five
new inference/API modules, and the frontend production build passed. The full
repository suite was not rerun; dependency deprecation and bundle-size warnings remain.
