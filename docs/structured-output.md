# Technical structured output

Technical tasks and NPC decisions share the existing LLM router's output policy.
Narration remains a text request. No second model, token-filtering framework or
additional generation loop is installed on the application machine.

## Contract and transport

The canonical Pydantic model remains the local validation contract. Its full
schema grounds a technical prompt when the selected mode or a deferred constraint
requires it. CHPM always includes its source-bound schema in the prompt.

A separate transient projection describes structural constraints the provider can
use during decoding. It does not replace stored state or introduce a parallel
extraction request:

- Conditional operation branches are expanded into complete alternatives. New
  state records and updates keep their different identity requirements.
- Finite scene-description conditions retain their environment-only restriction.
- Empty ID allowlists disable unavailable operations/arrays. They never permit a
  guessed ID. Required impossible roots fail before generation.
- Fixed homogeneous tuples keep their exact cardinality using ordinary array
  constraints. Unavailable references propagate through tuple positions too.
- Text patterns are retained in the canonical contract and checked locally.
  Whitespace-only wire fields use the canonical empty-string spelling.
- Collection constraints that some decoder backends ignore still have local
  validators. Schema conformance does not establish a fact's truth, visibility,
  ownership or exact source evidence.

Technical input examples and returned JSON bypass narration voice normalization.
Reasoning cleanup recognizes an outer prefix and preserves literal `<think>` or
`</think>` text inside a JSON value. Valid JSON also bypasses syntax repair, so
quoted fence markers and comma/bracket text remain unchanged. This preserves the
exact quotation that evidence validation subsequently checks.

Projection is not a general JSON Schema solver. Unsupported intersections or
conditions select a weaker supported mode before sending the request. An HTTP
error, timeout or uncertain remote request is not automatically resubmitted by
this policy. Existing bounded transport and proposal-repair rules still apply.

## Provider policy

| Connection | Technical output policy |
| --- | --- |
| Ollama | Native schema through its existing LiteLLM adapter, which maps the request to Ollama's `format`. Requires a supporting server/model. |
| llama.cpp / KoboldCpp / compatible cloud API | Honor the administrator's existing OpenAI-compatible setting: prompt only, JSON object or JSON schema. Schema mode uses the portable structural projection. |
| OpenAI | Strict schema for compatible closed contracts; JSON object when the task contract cannot be represented by this strict subset. |
| Google Gemini | Projected native JSON schema through the existing adapter. |
| Anthropic | Native schema or adapter-managed structured tool use for compatible closed contracts within the documented optional/union limits. Otherwise prompt-based JSON with local validation; a schema-less `json_object` is not presented as enforcement. |
| DeepSeek, Kimi, OpenRouter | Preserve the existing conservative JSON-object policy. DeepSeek beta strict tools are not silently enabled. Downstream OpenRouter capabilities still vary. |
| MiniMax | Preserve prompt-based JSON where the connection does not accept `response_format`. |

A shared endpoint does not make capabilities universal. The provider, selected
model, server/API version and task schema all matter. A small connection probe
does not certify all production schemas. Unsupported server-side constraints can
be rejected or ignored by a compatible API even when it returns HTTP 200.

## Settings and diagnostics

Connection settings display a compatibility notice for each role, outside the
collapsed generation settings. It explains prompt-only, JSON-only and native
schema limits. These notices are not inserted into RP messages or notifications.

Test Model uses one small structured request for every provider. It exercises the
technical output path while retaining the selected role's temporary endpoint and
sampling configuration; it does not save those temporary settings.

When system diagnostics are enabled, `llm.output_contract` records the requested
`output_mode`, a SHA-256 `schema_fingerprint` for schema requests and, when known,
the count of constraint categories deferred to local validation. The existing
request/call context ties this to the phase. The event records neither the schema
text nor the story, quotations or credentials. It describes the requested
contract, not proof of remote enforcement.

## Validation boundaries

Regression coverage checks exact limits, first-turn empty references, later known
references, operation identity, authored environment restrictions, tuple sizes,
canonical text validation and provider fallback boundaries. Adapter tests replace
HTTP before either httpx or aiohttp can open a socket, verify the translated
Ollama/OpenAI/Gemini/Anthropic/DeepSeek request and ensure freeform calls do not
inherit the technical format.

Mock HTTP and offline grammar conversion establish integration behavior. Live
tests are still needed for actual server enforcement, extraction accuracy, NPC
decision quality and latency.

## References

- [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs)
- [llama.cpp grammar limitations](https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md)
- [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Anthropic structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
- [DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode)
