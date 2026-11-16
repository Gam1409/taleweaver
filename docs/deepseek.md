# DeepSeek connection and output modes

Select the existing **DeepSeek** provider, save its API key in Administration,
and choose models independently for the application roles. No separate provider
is needed for JSON tasks. The native adapter uses Chat Completions and validates
structured responses against the application's Pydantic contracts.

Official documentation checked on 2026-11-09:

| Interface | Base URL / route | Purpose |
| --- | --- | --- |
| Chat Completions | `https://api.deepseek.com` + `/chat/completions` | Ordinary messages and JSON output; used by TaleWeaver |
| JSON Output | Same Chat Completions route | `response_format: {"type":"json_object"}`, not a separate URL |
| Beta features | `https://api.deepseek.com/beta` | Features such as assistant-prefix completion and strict tool schemas |
| Anthropic compatibility | `https://api.deepseek.com/anthropic` + `/v1/messages` | Different request/response protocol |
| Responses compatibility | `https://api.deepseek.com` + `/responses` | Responses API; TaleWeaver does not switch to it |

The current model list documents `deepseek-flash` and `deepseek-v4-pro`.
Refresh models rather than assuming historical model names remain current.

## JSON and validation

JSON Output needs an explicit JSON instruction; TaleWeaver's structured request
builder supplies that instruction and the expected schema. This guarantees no
domain semantics by itself: ownership, evidence, chronology and schema validation
still belong to the application. Not every technical subsystem uses the structured
builder: CHPM has its own bounded JSON text contract and validates its output.

The documentation permits whitespace-only JSON output and truncated output when
the generation budget is exhausted. An HTTP success is not proof of a valid
decision. Existing response and budget validation remains necessary. Strict tool
schemas are a separate beta feature with restricted schema support, including
limitations on string-length constraints; they cannot replace every application
schema unchanged.

## Thinking and sampling

DeepSeek enables thinking when both `thinking` and `reasoning_effort` are omitted.
TaleWeaver now explicitly sends `thinking.type=disabled` when the role's Thinking
setting is off, and `thinking.type=enabled` when on, for both text and structured
JSON calls. DeepSeek does not accept Anthropic's `budget_tokens` thinking control;
the native mode object contains only `type`. The application output cap still
limits generation. Separate reasoning-effort selection is not added by this fix.

Provider semantics matter: temperature and frequency/presence penalties are ignored
in thinking mode. Top P support differs by model and thinking mode. A visible
sampling control does not establish that a provider uses its value. See the
official compatibility table before comparing presets.

## Cache and concurrency

DeepSeek context caching is automatic and best effort. Stable prefixes and
persisted cache units matter; a partially overlapping prompt does not guarantee
a hit. Cache construction and eviction are server-managed. Inspect the returned
cache usage counters when available. Local application settings do not force
server cache residency.

[Per-role parallel request permissions](llm-parallel-requests.md) also support
native DeepSeek routing. They cap application concurrency; they do not increase
provider quotas or guarantee faster responses or stronger reasoning.

Sources: [overview](https://api-docs.deepseek.com/),
[Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/),
[JSON Output](https://api-docs.deepseek.com/guides/json_mode/),
[thinking](https://api-docs.deepseek.com/guides/thinking_mode/),
[prefix completion](https://api-docs.deepseek.com/guides/chat_prefix_completion/),
[tool calls](https://api-docs.deepseek.com/guides/tool_calls/),
[Anthropic compatibility](https://api-docs.deepseek.com/guides/anthropic_api/),
[Responses compatibility](https://api-docs.deepseek.com/guides/responses_api),
[context cache](https://api-docs.deepseek.com/guides/kv_cache/).

Verification uses mocked transport and the installed LiteLLM parameter mapper;
no live DeepSeek generation, billing or quality benchmark was performed.
