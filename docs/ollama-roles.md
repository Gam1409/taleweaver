# Independent Ollama settings for LLM roles

Ollama support remains experimental. Endpoint routing and valid transport do not establish a model's reliability for strict JSON or gameplay decisions.

Open **Administration → Intelligence (LLM)**. Each role has its own model selection and three optional connection overrides under **General settings → Connection settings**:

| Role | Use | Settings prefix | Default timeout |
| --- | --- | --- | --- |
| `small` | Mechanics and short helpers | `small_` | `INTELLIGENCE_TIMEOUT` |
| `complex` | Narration and editor validation | `complex_` | `INTELLIGENCE_TIMEOUT` |
| `generator` | World generation | `generator_` | `WORLDBUILDING_TIMEOUT` |
| `compression` | History summary | `compression_` | `INTELLIGENCE_TIMEOUT` |
| `play_agent` | Autonomous player | `play_agent_` | `INTELLIGENCE_TIMEOUT` |

Append `ollama_url`, `ollama_timeout`, or `ollama_num_ctx` to the prefix. These 15 fields live in the existing JSON settings column and need no database migration. Settings are global and are broadcast to other users through the existing settings workflow.

A blank role URL inherits `ollama_url`, then `http://localhost:11434`. Timeout accepts 30–600 seconds; blank uses the environment default (`INTELLIGENCE_TIMEOUT`, 60 seconds by default, or `WORLDBUILDING_TIMEOUT`, 600 seconds for the generator). Context size accepts 512–1048576 tokens; blank leaves the model/server default. Clearing a numeric input sends `null`. Servers and model names can be shared or different for any pair of roles.

Editing the global Ollama API Host in Intelligence settings copies that URL into all five role URL fields, including roles currently using another provider, replacing previous overrides. You can then edit individual role URLs in General settings. Save applies the resulting values. Loading or reopening saved settings preserves individual URLs; it does not copy the global URL again.

Model discovery is cached by effective URL. Refresh in a role queries that URL. Manual model names remain available, including for compression. Test sends the selected role and its unsaved URL, model, timeout, context size and API mode; the server restores the original settings after the request and performs no commit. New role URLs and submitted test URLs pass the existing provider URL validation, including the private-network policy.

Timeout is per attempt. Guarded self-hosted requests do not automatically retry an
unconfirmed transport failure. Other provider paths may retry transient failures;
see [inference queue](inference-queue.md). A proxy can impose a shorter timeout.
Editor AI Fix inherits the selected role's timeout by default. An explicitly set
`AI_FIX_SUGGEST_TIMEOUT_SECONDS` remains a separate watchdog; remove a legacy
`=90` entry from your environment to inherit the configured role deadline.

## Routing and compatibility

`resolve_llm_role` selects a provider and model as a pair. `GameMasterLLM.for_role(user, role)` constructs the router and exposes the selected `model`. Callers send this model rather than inventing a separate default.

| Requested role | Provider donor order | Cloud model default |
| --- | --- | --- |
| `small` | small → complex → preferred → OpenAI | `gpt-4o-mini` |
| `complex` | complex → small → preferred → OpenAI | `gpt-4o` |
| `generator` | generator → complex → small → preferred → OpenAI | `gpt-4o` |
| `compression` | compression → small → OpenAI | `gpt-4o-mini` |
| `play_agent` | play_agent → small → complex → preferred → OpenAI | `gpt-4o-mini` |

A donor contributes both provider and model; a stale model from the requested role cannot be combined with another role's provider. This intentionally corrects the previous independent fallback chains, including incomplete cloud configurations. Explicit provider/model selections and the cloud default names are preserved. Ollama with a blank model raises `No model configured for role '<role>' (provider 'ollama').` before making a request.

Runtime connection overrides belong to the requested role, including when its provider/model is inherited. The legacy constructor remains supported and only applies role overrides when both its actual provider and the configured role provider equal `ollama`. Play Agent has its own URL, timeout and context, while retaining the existing small-role token and thinking settings. Editor AI-fix tries complex and small as distinct roles even when they use the same provider/model name on different servers; its environment fallback has no role overrides.

Every Ollama request path uses `_apply_ollama_options`. `num_ctx` is a top-level LiteLLM argument; `max_tokens` remains separate and becomes `options.num_predict`. There is no `extra_body.options` replacement. The saved `ollama_api_mode` selects Generate (`ollama`, `/api/generate`) or Chat (`ollama_chat`, `/api/chat`) for all Ollama roles. Generate remains the compatibility default. Admission and retries follow the [inference queue policy](inference-queue.md). The router explicitly sends the role's thinking flag, including `false`; model templates may still emit reasoning despite that setting.

## Assessment of `ollama_chat`

The installed LiteLLM adapter was tested against a local fake Ollama HTTP server, through all five router paths: synchronous and asynchronous text, streaming, and synchronous and asynchronous Pydantic responses. Both `ollama` and `ollama_chat` passed. Both preserved `options.num_ctx`, `options.num_predict`, the thinking flag, and the structured-output schema in `format`. The chat transport used `/api/chat` and preserved system/user/assistant history roles; generate used `/api/generate` with a flattened prompt. The tests are in `tests/test_ollama_transport.py` and exercise the saved API mode.

Chat preserves separate system/user/assistant messages; Generate uses a flattened
prompt. Choose the mode supported by the installed model and server, then compare
repeated equivalent turns. The [historical live-test report](ollama-roles-report.md)
records a small model-specific comparison; its latency and success counts are not
a benchmark or certification of current models or code.

For structured tasks, keep a schema-bearing `response_format`: LiteLLM maps it to Ollama's native `format`. Ordinary text requests do not need it. A JSON instruction alone can request JSON, but cannot enforce the response schema. This is separate from the custom OpenAI-compatible provider's optional capability modes, which remain unchanged.

## Direct API access through a user-managed SSH tunnel

TaleWeaver does not manage SSH credentials or tunnels. Start the tunnel on the machine running the backend, using your own host, port and private-key path:

```bash
ssh -N -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:11434:127.0.0.1:11434 \
  -p SSH_PORT -i /path/to/private_key SSH_USER@SSH_HOST
```

Set the application's Ollama URL to `http://localhost:11434`. If that local port is already used, choose another local port and use it in the URL. Enable `ALLOW_PRIVATE_NETWORK_MODELS=true` in the backend environment when using role URLs or connection tests against a private address. In Docker, `localhost` refers to the backend container: the tunnel must be reachable from that container, with its URL adjusted accordingly.

A tunnel connected through its local port avoids the public HTTP proxy on that
route. It does not override TaleWeaver's request limit or the inference server's
own deadline. A larger role timeout cannot extend a proxy's shorter deadline.
Earlier tunnel/proxy experiments are recorded in the historical report; verify
your own forwarding and container route before relying on a long generation.

## Implementation owners

- [Role/provider/model resolution](../backend/core/llm_roles.py).
- [Ollama override validation and defaults](../backend/core/ollama_role_config.py).
- [Shared LLM router](../backend/core/llm_router.py).
- [Role connection UI](../frontend/src/components/admin/OllamaRoleSettings.vue).

The [original 30-call-site audit](ollama-roles-report.md#original-call-site-audit-historical)
is retained as a historical implementation record. Its old file locations and
line numbers are not a current call-graph index.

## Remaining limitations

The shared legacy `ollama_url` lacks save-time and router-time URL validation. Role overrides and submitted test URLs use the shared validator; see the exact [provider network policy](provider-network-policy.md). The additional AI-Fix environment fallback is now disabled by default. Explicitly setting `AI_FIX_FALLBACK_PROVIDER=openai` can send adventure content to that service; see [AI-Fix provider policy](ai-fix-providers.md). Image, TTS and STT have separate configuration and transport paths.

## Discovering models for a role URL

Each role's Ollama settings has a **Check models at this URL** button beside the URL.
Opening settings or editing a role URL automatically refreshes its model list after
600 ms without further edits. Results are cached by normalized server URL and used
only by roles pointing to that server; discovery never changes a selected model.
The status shows the returned model count, or asks you to check the address/server
when no models were returned. An empty role URL uses the global Ollama URL.
Save the settings to persist the chosen URL and model. Runtime requests use the
saved role URL; discovery alone does not save the form.

## Verification

Role-resolution, connection and wire-transport coverage lives in
`tests/test_llm_roles.py`, `tests/test_config_api.py` and
`tests/test_ollama_transport.py`.
Tests use mocked endpoints or local fake servers. See the repository's current
CI reports for the checked revision and the historical report for earlier live
experiments; neither discovery nor an HTTP success certifies gameplay quality.
