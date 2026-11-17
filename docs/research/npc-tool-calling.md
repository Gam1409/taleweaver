# NPC tool calling: implementation review and design evidence

Status: engineering research, 17 November 2026. This records upstream guidance
and a source review, not measured improvements on a particular inference server.
The first implementation adds discovery, room reads and clearer tool feedback.
World-action execution remains the subsequent integration described below.

Verification for this first wave: 1,504 offline CHPM/game-loop/layering checks
passed, including real SQLite turn publication for both wire formats. Backend
mypy passed for 1,089 source files. The private live preparation has 184 offline
checks and 33 planned scenarios; this is not a completed live evaluation or a
claim that the new world-action API has been implemented.

## Findings from primary sources

| Source | Relevant finding | Application here |
| --- | --- | --- |
| [Hugging Face tool use](https://huggingface.co/docs/transformers/en/chat_extras) and [chat templates](https://huggingface.co/docs/transformers/en/chat_templating) | Models learn specific message/control-token formats. The assistant call and its tool result must both reach the next generation. Transformers arguments are objects; OpenAI wire arguments are JSON strings. | Keep structured messages through the provider adapter. Do not double-render them with a client Jinja template or stringify arguments twice. |
| [llama.cpp function calling](https://github.com/ggml-org/llama.cpp/blob/master/docs/function-calling.md) | Native and generic format handlers differ. Tool-aware templates and parser selection matter; generic formatting may consume more tokens. Aggressive KV quantization can degrade tool use. | Check server version, actual model template and parser before attributing a malformed call to model intelligence. A valid GGUF chat template need not support tool results correctly. |
| [Qwen function calling](https://qwen.readthedocs.io/en/latest/framework/function_call.html) | Qwen documents a model-specific tool format and recommends Hermes-style tool use for Qwen3. | Use the selected model's supported template, rather than assuming that a different family's XML/JSON markers transfer. |
| [Gemma function calling](https://ai.google.dev/gemma/docs/capabilities/text/function-calling-gemma4) and [FunctionGemma](https://ai.google.dev/gemma/docs/functiongemma/function-calling-with-hf) | Tool definitions enter through the chat template. FunctionGemma uses a specialized tokenizer/chat format. The application validates and executes calls. | A model family name is insufficient to choose a template or establish reliable tool support. Never execute generated source code as an action. |
| [KoboldCpp upstream Wiki](https://github.com/LostRuins/koboldcpp/wiki) and [maintainer discussion #2549](https://github.com/LostRuins/koboldcpp/issues/2549) | Template and universal-tool behavior depend on version. The Wiki describes separate Jinja flags, while maintainers describe their consolidation in 1.123.1. | Record the actual version and inspect its options. Do not prescribe llama.cpp flags to KoboldCpp or treat an old Wiki flag as universally current. |
| [Anthropic: writing effective tools](https://www.anthropic.com/engineering/writing-tools-for-agents) | Distinct purposes, efficient bounded responses, clear identifiers and actionable errors improve the interface available to an agent. More overlapping tools are not inherently better. | Prefer short domain commands and targeted reads. Offer available capabilities, distinguish unknown from empty, and explain how to correct errors. This is design guidance, not a guaranteed gain for a small local model. |
| [Berkeley BFCL V3](https://gorilla.cs.berkeley.edu/blogs/13_bfcl_v3_multi_turn.html) | Multi-step evaluation checks actual API state and necessary read paths; matching one function signature is insufficient. | Verify final ownership, location, wear and remaining resources, as well as actual tool invocation and recovery. Accept different valid action sequences. |

## Current implementation inventory

`core/llm_tool_turn.py` retains native assistant calls, call IDs and raw argument
strings; the common provider adapter owns HTTP transport. CHPM's native and JSON
ports use the same validated capability dispatcher. Integrated operation requires
the final `submit_decision` to be alone. All call arguments are validated before
executing a batch. Notebook writes are staged, revision checked and published at
their established boundary. Transport failures do not trigger uncertain replays.

The application currently does not render model Jinja templates. That belongs to
the inference server/tokenizer. Advertising OpenAI-compatible `tools` is not proof
that the deployed server/model/template understands them. The existing automatic
mode checks local adapter support, not remote semantic competence.

The review identified concrete host interface gaps:

1. The bounded initial entity index can omit a perfectly accessible item, and
   there was no current-entity name search. Memory search does not solve this:
   historical mention cannot establish current custody or provide a new identity.
2. `visible_clothing` is restricted to listed NPCs, but its native description
   did not explain the player-inspection alternative. An unavailable actor result
   gave no corrective path.
3. A separate room read was missing even though scene and movement owners already
   provide the necessary scoped facts and route validation.
4. Tool results retained their call IDs but omitted the optional function name.
   Both native loops now retain the name too, for templates that display it.
5. Adding descriptions and schemas can exceed an existing context budget. The
   implementation offers new read surfaces only when available, omits unusable
   NPC-clothing tools and removes redundant lookup schema annotations. Budgets
   and inference request limits are unchanged.

These changes do not prove that a particular server template was previously
wrong, or that prose, psychological choices or action execution are now reliable.
In particular, Integrated still submits the full cognitive proposal. A tool-aware
template cannot remove that proposal's semantic constraints.

## Recommended action interface

Use [the subsystem ownership standard](../engineering/subsystem-contracts.md).
The model supplies a short command, never a replacement inventory or whole-world
JSON object. The host supplies the bound actor/session and preserves canonical
IDs. A lookup does not grant permission to take another character's possession.

| User capability | Existing owner | Required command integration |
| --- | --- | --- |
| Find; inspect self/person/item/room | Observer-local CHPM projections, clothing and condition views, movement context | Discovery and scoped reads; preserve private/unknown state and omission counts. |
| Move between rooms | Movement permissions/routes and `TurnStateApplier` | Validate current directed route, effective lock, mobility and controller. Never move the player as a side effect. |
| Take, give, place/drop | Canonical possession snapshot, transfer and ownership owners | Exact existing ID; validate custody/access at application, preserve metadata and clear only affected worn/placement references. |
| Wear, remove, partly wear/remove | Clothing profile/coverage owner | Owned garment, known wear/coverage, existing policy gates. Partial displacement stays worn; removal retains ownership. |
| Change an item's mutable state | Physical/item-condition owner | Reuse condition identity and dimension; preserve immutable appearance and unrelated properties. A free-form property must not grant powers. |
| Partly or fully use an item | Item rules, scripted effects and possession/condition owners | Determine the item's supported effect and resources first. Using a reusable object is not consuming it; unknown quantity is not a full resource. |

Important demonstrated integration gap: existing narration validators require
exact completed-prose evidence. They cannot honestly accept an unperformed command
by manufacturing a narration quote. A command needs its own typed authorization
and authoritative result boundary inside the existing owners.

Cognitive jobs can run concurrently and intentionally avoid database access.
Do not execute mutations in those jobs or commit independently during a model
wait. Prepare action intents locally; coordinate application through the turn's
existing mutation lease, recovery snapshot and domain owners. Recheck custody,
location, controller and source freshness at that boundary. Two NPCs cannot both
acquire the same item just because both saw it before deciding.

The result must distinguish `proposed`, `applied`, `blocked`, `stale` and
`unconfirmed`; only an applied receipt establishes a completed world action.
Before narration, provide authoritative outcomes separately from selected motives
and intended actions. Failed/cancelled turns, regeneration, replay, copy/import
and Undo must preserve the existing owner-specific lifecycle. Partial clothing
and condition provenance need explicit compatibility tests when a command-source
contract is introduced. No universal setter, remote execution or arbitrary file
access is part of this interface.

For small models, prefer operation-specific schemas with few arguments, one
mutation at a time, host-derived identity/defaults and structured error feedback.
Permit independent reads in the existing bounded batches. Expose capabilities
based on mechanical availability, not on a host prescription of what the NPC
should want. Keep tool selection separate from personality and player agency.

## Template and behavior evaluation

For a future authorized live run, record model/tokenizer revision, inference-server
version, template source, parser/format, quantization, sampling and context size.
Do not infer these from `/v1/models` alone. Use a neutral two-turn probe:

1. Offer an `inspect_item(item_id)` function and request a known item.
2. Require a parsed call with the exact ID. Return a synthetic state such as a
   sealed flask; include matching call ID and function name.
3. Check that the next response uses that returned state, rather than repeating
   the call or guessing a different result. Keep a prompt-injection canary inside
   tool data to verify it does not become a new instruction.

Compare native tools with the model's verified template against existing JSON
compatibility on the same tasks. Then test short and long contexts, unnecessary
tool abstention, find→inspect→act chains, failed calls followed by correction,
blocked routes, stale custody, conflicting actors, partial wear/use and replay.
Check actual world state plus necessary read invocations. Track completion,
rejections, recoveries, requests, tokens and elapsed time separately. Grammar
validity and a single successful call do not establish multi-step reliability.

Prose quality and emotional expression are a separate subsequent evaluation.
Keep the complete emotional/context handoff, but do not force technical tool
receipts or inventory syntax into character dialogue.
