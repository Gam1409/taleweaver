# NPC tool-calling compatibility profiles

In **Session settings → NPC Personality**, select a **Tool-calling profile**
alongside **Agent tool compatibility** or **Memory tool compatibility**.
Adventure defaults expose the same controls for new sessions. Existing sessions
keep their own selection; old settings default to `tool_profile: "auto"`.

A profile chooses compatibility policy for the existing tool port. It does not
change the configured provider, model, endpoint, workflow, NPC identity, available
actions or request limits. It does not install a serving template or parser.
Model weights, API dialect and serving runtime are separate compatibility inputs:
for example, mistral.rs can serve several model families.

## Profiles and protocols

| Profile | Automatic tool compatibility | Explicit Native function calls |
| --- | --- | --- |
| Auto | Preserves the existing configured native-support check and JSON fallback before dispatch. No family inference from a model name. | Requires the existing native adapter support. |
| Anthropic | Uses the existing provider adapter and native-support check; falls back to JSON before dispatch when unsupported. | Requires the existing native adapter support. |
| OpenAI | Uses the existing provider adapter and native-support check; falls back to JSON before dispatch when unsupported. | Requires the existing native adapter support. |
| Mistral | Uses the existing provider adapter and native-support check; falls back to JSON before dispatch when unsupported. | Requires the existing native adapter support. |
| Gemma | Selects JSON compatibility conservatively. The reviewed native templates cannot represent the full cognitive and notebook declarations losslessly. | Checks the actual offered parameter schemas before reserving a request. Unsupported declarations are rejected locally. |
| DeepSeek | Uses the existing provider adapter and native-support check; falls back to JSON before dispatch when unsupported. | Requires the existing native adapter support. |
| Qwen | Selects JSON compatibility conservatively. Native argument typing depends on the model family, parser and runtime version. | Checks the actual offered parameter schemas before reserving a request. Unsupported declarations are rejected locally. |

Where the native/portable selector is used, **JSON compatibility** explicitly
selects the same portable JSON port for every profile. The legacy Auto/Staged
exception is described below. For Gemma and Qwen, explicit native mode accepts
only simple typed, closed parameter shapes allowed by local preflight; references,
compositions, untyped values and open JSON
dictionaries are rejected. This examines schema positions, not literal values
inside `const` or `enum`. Simple tools can therefore be eligible even when the
full cognitive submission or private notebook tools are not.

An incompatible explicit native request explains how to select **Automatic** or
**JSON compatibility** while keeping the selected family profile. It consumes no
model request. The chosen port stays fixed during the tool conversation; an
uncertain request is never resent using another protocol.

For the Auto profile, Staged lookup without private notebooks retains its legacy
JSON lookup planner. A non-Auto profile uses the selected native/portable port
for Staged lookup even with notebooks disabled. Integrated decisions and RPG
ability selection use the same profile owner. These choices do not enable action
tools in Staged or bypass combat initiative.
RPG ability declarations retain their existing strict schemas; selecting a profile
does not enable strict mode for arbitrary notebook values.

## Shared execution contract

Every profile retains the same host-bound actor and session, offered functions,
whole-batch argument validation, correlated tool results, source budgets, deadlines
and request accounting. Tool text is data. Only existing validated world owners
publish actions; a preview or model proposal is not an accomplished world fact.
Private notebook values remain freely organized JSON rather than a family-specific
memory schema.

Native functions and structured textual output are separate interfaces. Native
calls need a tool-aware template/parser that preserves declarations and arguments.
JSON compatibility includes the same tool catalog in a text request. Its output
format follows the existing provider output setting; selecting a family does not
silently turn on a server grammar. Where a structural decoder requires explicit
types, unrestricted JSON is represented with all six JSON kinds rather than an
object-only substitute. Local canonical validation still decides acceptance.

When the configured provider policy selects JSON Schema, the portable port also
binds each function name to its canonical parameter schema. This prevents a
well-formed envelope from accepting an incomplete decision or arguments belonging
to another tool. Local definition references retain each tool's scope; arbitrary
notebook JSON remains unrestricted. The selected schema counts against the
existing input-character allowance. Unsupported reference scopes or provider
projections retain the existing envelope constraints and log a warning rather
than silently claiming argument enforcement. Prompt and JSON-object modes keep
their existing behavior.

Changing a profile preserves minds, memories, dormant preferences and existing
request limits. Standard, Observe, disabled rounds and unsupported game-mode
combinations do not become new autonomous execution paths.

## Compatibility limits

A family label is not certification of every model or server version. The four
native-preferring vendor profiles reuse the shared adapter; they do not introduce
four new clients or override model-specific reasoning controls. Providers can
require opaque thinking/signature data to be replayed, and adapters can transform
or omit metadata. A local native-support check cannot establish that an arbitrary
remote template renders every declaration correctly.

In particular, Qwen's Hermes and XML families require different serving parsers;
Gemma requires its tool-aware template and supported declaration shapes. Strict
closed-object APIs cannot faithfully represent arbitrary notebook JSON. Do not
repair those mismatches by dropping argument types, closing free dictionaries,
coercing all values to strings, raising request limits or retrying an uncertain
call. Select a compatible runtime/configuration or the portable JSON path.

Offline tests verify routing, schema representation, pre-dispatch rejection,
legacy loading and persistence. They do not demonstrate that a live model chooses
sensible actions, follows the tool protocol reliably or expresses emotions well.
Matched live evaluation must record the actual provider, model, runtime, template,
profile, protocol and output configuration separately.

## Official references

Reviewed on 2026-11-17. These describe upstream interfaces, not a guarantee that
every installed adapter or local model implements their latest version.

- [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling)
  and [structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
- [Anthropic client tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools)
  and [thinking with tools](https://platform.claude.com/docs/en/build-with-claude/thinking-tool-workflows).
- [Mistral function calling](https://docs.mistral.ai/inference/conversations/function-calling)
  and the separate [mistral.rs runtime guide](https://ericlbuehler.github.io/mistral.rs/guides/agents/tool-calling-basics/).
- [Gemma function calling](https://gemma.ai/get-started/capabilities/function-calling/?model=gemma-4%2F31b)
  and the [official 31B example](https://github.com/google-gemma/docs/blob/main/docs/notebooks/function-calling-gemma-4-31b.ipynb).
- [DeepSeek tool calls](https://api-docs.deepseek.com/guides/tool_calls/)
  and [thinking mode](https://api-docs.deepseek.com/guides/thinking_mode).
- [Qwen function calling](https://qwen.readthedocs.io/en/latest/framework/function_call.html)
  and [vLLM deployment](https://qwen.readthedocs.io/en/latest/deployment/vllm.html).
