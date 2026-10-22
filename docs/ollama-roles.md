# Independent Ollama settings for LLM roles

Ollama support remains experimental. This change configures and routes models; it does not establish their reliability for strict JSON or improve model quality by itself.

Each Intelligence role has its own existing model selection and three optional settings in an **Ollama settings (experimental)** accordion, collapsed by default:

| Role | Use | Settings prefix | Default timeout |
| --- | --- | --- | --- |
| `small` | Mechanics and short helpers | `small_` | `INTELLIGENCE_TIMEOUT` |
| `complex` | Narration and editor validation | `complex_` | `INTELLIGENCE_TIMEOUT` |
| `generator` | World generation | `generator_` | `WORLDBUILDING_TIMEOUT` |
| `compression` | History summary | `compression_` | `INTELLIGENCE_TIMEOUT` |
| `play_agent` | Autonomous player | `play_agent_` | `INTELLIGENCE_TIMEOUT` |

Append `ollama_url`, `ollama_timeout`, or `ollama_num_ctx` to the prefix. These 15 fields live in the existing JSON settings column and need no database migration. Settings are global and are broadcast to other users through the existing settings workflow.

A blank role URL inherits `ollama_url`, then `http://localhost:11434`. Timeout accepts 30–600 seconds; blank uses the environment default. Context size accepts 512–1048576 tokens; blank leaves the model/server default. Clearing a numeric input sends `null`. Servers and model names can be shared or different for any pair of roles.

Editing the global Ollama API Host in Intelligence settings copies that URL into all five role URL fields, including roles currently using another provider, replacing previous overrides. You can then edit individual role URLs in their advanced settings. Save applies the resulting values. Loading or reopening saved settings preserves individual URLs; it does not copy the global URL again.

Model discovery is cached by effective URL. Refresh in a role queries that URL. Manual model names remain available, including for compression. Test sends the selected role and its unsaved URL, model, timeout, context size and API mode; the server restores the original settings after the request and performs no commit. New role URLs and submitted test URLs pass the existing provider URL validation, including the private-network policy.

Timeout is per attempt; failed requests are retried up to 3 times. With the existing retry policy, the total can approach `4 × timeout + 4.5 seconds`. The bundled nginx proxy has a 300-second read timeout, and editor AI-fix has a separate `AI_FIX_SUGGEST_TIMEOUT_SECONDS` watchdog (90 seconds by default).

## Routing and compatibility

`resolve_llm_role` selects a provider and model as a pair. `GameMasterLLM.for_role(user, role)` constructs the router and exposes the selected `model`. Callers send this model rather than inventing a separate default.

| Requested role | Provider donor order | Cloud model default |
| --- | --- | --- |
| `small` | small → complex → preferred → OpenAI | `gpt-4o-mini` |
| `complex` | complex → small → preferred → OpenAI | `gpt-4o` |
| `generator` | generator → complex → small → preferred → OpenAI | `gpt-4o` |
| `compression` | compression → small → OpenAI | `gpt-4o-mini` |
| `play_agent` | play_agent → small → complex → preferred → OpenAI | `gpt-4o-mini` |

A donor contributes both provider and model; a stale model from the requested role cannot be combined with another role's provider. This intentionally corrects the previous independent fallback chains, including incomplete cloud configurations. Explicit provider/model selections and the cloud default names are preserved. Ollama with a blank model raises `No model configured for role '<role>' (provider 'ollama').` before making a request. World generation retains its existing error when no generator provider can be resolved.

Runtime connection overrides belong to the requested role, including when its provider/model is inherited. The legacy constructor remains supported and only applies role overrides when both its actual provider and the configured role provider equal `ollama`. Play Agent has its own URL, timeout and context, while retaining the existing small-role token and thinking settings. Editor AI-fix tries complex and small as distinct roles even when they use the same provider/model name on different servers; its environment fallback has no role overrides.

Every Ollama request path uses `_apply_ollama_options`. `num_ctx` is a top-level LiteLLM argument; `max_tokens` remains separate and becomes `options.num_predict`. There is no `extra_body.options` replacement. The saved `ollama_api_mode` selects Generate (`ollama`, `/api/generate`) or Chat (`ollama_chat`, `/api/chat`) for all Ollama roles. Generate remains the compatibility default. Retries are unchanged. The router explicitly sends the role's thinking flag, including `false`; model templates may still emit reasoning despite that setting.

## Assessment of `ollama_chat`

The installed LiteLLM adapter was tested against a local fake Ollama HTTP server, through all five router paths: synchronous and asynchronous text, streaming, and synchronous and asynchronous Pydantic responses. Both `ollama` and `ollama_chat` passed. Both preserved `options.num_ctx`, `options.num_predict`, the thinking flag, and the structured-output schema in `format`. The chat transport used `/api/chat` and preserved system/user/assistant history roles; generate used `/api/generate` with a flattened prompt. The tests are in `tests/test_ollama_transport.py` and exercise the saved API mode.

**Recommendation for the tested Qwen/Artemis pair:** use the opt-in Chat mode, retaining Generate for comparison and rollback. In 29 repeated live calls with thinking disabled, all 24 Qwen calls completed across four roles and both transports. Qwen's observed median was 2.38 seconds for Generate and 1.99 seconds for Chat; these small, warm-cache samples are not a controlled performance benchmark. Artemis Chat returned useful narration in three of three calls; Generate returned useful narration once and failed on the second attempt. Earlier calls without the explicit thinking flag included empty or reasoning-only narration.

Chat does not guarantee coherent game mechanics. Live gameplay exposed a mismatch between narration and persisted location, and reasoning text appeared in ordinary Qwen compression responses with both transports. Cleanup now handles a closing `</think>` tag whose opening tag was supplied by a model template. See the [implementation and live-test report](ollama-roles-report.md) for quality findings and limits.

For structured tasks, keep a schema-bearing `response_format`: LiteLLM maps it to Ollama's native `format`. Ordinary text requests do not need it. A JSON instruction alone can request JSON, but cannot enforce the response schema. This is separate from the custom OpenAI-compatible provider's optional capability modes, which remain unchanged.

## Direct API access through a user-managed SSH tunnel

TaleWeaver does not manage SSH credentials or tunnels. Start the tunnel on the machine running the backend, using your own host, port and private-key path:

```bash
ssh -N -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:11434:127.0.0.1:11434 \
  -p SSH_PORT -i /path/to/private_key root@SSH_HOST
```

Set the application's Ollama URL to `http://localhost:11434`. If that local port is already used, choose another local port and use it in the URL. Enable `ALLOW_PRIVATE_NETWORK_MODELS=true` in the backend environment when using role URLs or connection tests against a private address. In Docker, `localhost` refers to the backend container: the tunnel must be reachable from that container, with its URL adjusted accordingly.

Direct access avoids the public RunPod HTTP proxy's timeout. A larger role timeout cannot extend an upstream proxy's deadline. During live testing, a non-streaming world request received HTTP 524 at about 126 seconds. A test-only streaming adapter allowed the same application pipeline to complete a small world in 166.5 seconds; that adapter is not included in this change. Direct SSH access from the cloud test environment was refused, so the tunnel path has not been verified end to end.

## Call-site audit

The specification's 30 original locations map to the following current code. Several monolithic files had already been split into helpers before this change; repeated rows represent their original callers.

| # | Specification location | Current implementation | Role |
| --- | --- | --- | --- |
| 1 | `agent_logic.py:211` | `agent_logic.py`, agent decision | `play_agent` |
| 2 | `editor.py:1871` | `editing/ai_fix_llm.py` | candidate `complex` / `small`; environment fallback has no role |
| 3 | `editor.py:699` | `editing/validation.py` | `complex` |
| 4 | `config_api.py:1264` | `/settings/test-llm` | request role, default `small` |
| 5 | `gameplay_logic.py:1186` | mechanics pass | `small` |
| 6 | `gameplay_logic.py:1433` | generator tool intent pass | `small` |
| 7 | `gameplay_logic.py:1525` | chat progression pass | `small` |
| 8 | `gameplay_logic.py:1692` | narration pass | `complex` |
| 9 | `turn_combat.py:266` | `combat/narration.py::_complex_llm`, aftermath | `complex` |
| 10 | `turn_combat.py:659` | `combat/narration.py::_complex_llm`, special event | `complex` |
| 11 | `turn_adventure_gen.py:489` | terminal epilogue | `complex` |
| 12 | `gameplay_logic.py:2208` | history compression | `compression` |
| 13 | `turn_guardrails.py:143` | `guardrails/base.py::_small_llm` (inspect/items/reveals) | `small` |
| 14 | `turn_guardrails.py:985` | same shared guardrails helper | `small` |
| 15 | `turn_guardrails.py:1115` | same shared guardrails helper | `small` |
| 16 | `turn_suggestions.py:227` | prompt suggestions | `small` |
| 17 | `turn_adventure_gen.py:106` | short intent classification | `small` |
| 18 | `gameplay.py:755` | translation | `small` |
| 19 | `assets.py:355` | image prompt suggestion | `small` |
| 20 | `templates.py:445` | story idea | `small` |
| 21 | `templates.py:696` | template field generation | `small` |
| 22 | `users_api.py:232` | biography generation | `small` |
| 23 | `editor.py:3644` | `editing/generation.py::_small_llm` | `small` |
| 24 | `editor.py:3689` | same shared editor generation helper | `small` |
| 25 | `editor.py:3743` | same shared editor generation helper | `small` |
| 26 | `editor.py:3795` | same shared editor generation helper | `small` |
| 27 | `editor.py:3839` | same shared editor generation helper | `small` |
| 28 | `editor.py:3890` | same shared editor generation helper | `small` |
| 29 | `world_generator.py:497` | `WorldGenerator.generate_world` | `generator` (explicit overrides retained) |
| 30 | `templates.py:637` | surprise preset | `generator` |

`TurnLlmContext` also obtains its small, complex and compression choices through `turn_context_helpers.resolve_model_settings`, which uses the shared resolver. No production role caller retains a direct `GameMasterLLM(...)` construction; the sole exception is the intentionally role-free environment fallback.

## Remaining limitations

The global legacy `ollama_url` still lacks save-time and router-time SSRF validation. This task validates the new role URLs and submitted test URLs without changing that older policy. `AI_FIX_FALLBACK_PROVIDER=openai` with the default `gpt-4o-mini` can send adventure content to a cloud service after a local failure if an OpenAI key is configured; setting the fallback provider to an empty value disables that environment fallback. Image, TTS and STT providers are unchanged. No dependency lock files were modified.
