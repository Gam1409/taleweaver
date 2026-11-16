# Subsystem responsibilities and contracts

This is the project standard for new work and changes to existing integrations.
It applies to human contributors and coding agents through
[AGENTS.md](../../AGENTS.md) and the
[contributor instructions](../../.github/copilot-instructions.md).

TaleWeaver is a modular monolith. Its subsystems share a backend, persistence and
inference infrastructure. A module boundary therefore needs explicit ownership
and contracts; a directory name alone cannot isolate its effects. Existing legacy
coupling remains visible in the [engine boundary](engine-boundary.md) and
[complete turn lifecycle](turn-lifecycle.md). This standard does not claim that
every rule below is already enforced automatically across the codebase.

## 1. State authority

Every fact or operation has a logical owner. An owner can span existing packages
and entry points; it does not require a new service, database or registry.
Consumers use the owner's validated operations or an appropriate read projection.
Sharing SQLite, session JSON or an ORM object does not grant mutation authority.

Keep these categories distinct:

- **Canonical state:** accepted world, character, possession and source records.
- **Proposals:** model intents, extracted effects and selected NPC intentions
  awaiting their applicable validation and publication boundaries.
- **Subjective records:** beliefs, experiences, rumors and private notes with
  their own audience and provenance; they are not automatically objective facts.
- **Derived views and artifacts:** recall indexes, display cues, visual snapshots,
  prompts and generated media. Their existence does not establish a world action.

When reading another subsystem, obtain the view for the actual audience. A GM
context, public UI, observing NPC and image generator have different access rules.
An omitted, inaccessible or unassessed fact is not an empty, absent or healed fact.

## 2. Responsibility map

The following groups identify existing owners, rather than introducing a new
runtime hierarchy. Their detailed limits and gates remain in their linked guides.

| Subsystem | Responsibility and accepted effects | Boundary to preserve |
| --- | --- | --- |
| [API and frontend transport](frontend-transport.md) | Authentication, ownership checks, request/response contracts, cancellation and delivery. Routes dispatch to domain services. | Engine code must not depend on API-route implementations. A progress event or browser notification is not a commit receipt. |
| [Turn orchestration](turn-lifecycle.md) | Mode selection, phase order, resolution context and coordination of existing persistence/recovery owners. | Delegate domain checks and mutations; do not grow the legacy manager into a second implementation of each subsystem. |
| Rules, combat and [scripts](../scripting_engine.md) | Deterministic access requirements, rolls, effects, progression and supported script changesets. See [state application](../../backend/engine/gameplay/turn_state_applier.py). | Model wording cannot replace rule checks. Retain mode restrictions, hook order and the existing validated mutation paths. |
| [Possessions and clothing](../narrated-item-reconciliation.md) | Canonical item identity, ownership, transfer, wear, coverage and supported placement through the existing inventory/clothing owners. | Carrying, wearing and appearance are separate. Reuse existing IDs and validate participants and complete same-item chains. |
| [Physical and item conditions](../persistent-physical-state.md) | Source-bound current conditions and [mutable item properties](../item-state.md), their operations, visibility and history. | Narrative omission, a new image or a different consumer view cannot silently resolve or replace a condition. |
| [Scenes and movement](../narrated-movement.md) | Canonical location, route access, presence and validated actor/player travel. | A pose, remembered identity or NPC plan does not move an actor or choose the player's response. |
| [Room continuity](../../backend/engine/scene_continuity/runtime.py) and [staging](../scene-staging.md) | Source-bound room facts and consequences; separately, derived pose/prop views. | Preserve the distinction between canonical room records and derived staging. A spatial presentation does not grant ownership or physical access. |
| [NPC Personality](../npc-decision-workflows.md) | Observer-local psychology, evidence, intentions and reviewed publication; separately enabled [private notebooks](../npc-notebook.md). | Reads and notes do not execute or reserve world actions. Physical outcomes use the world owners; private knowledge remains scoped. |
| [Living World](../living-world-architecture.md) | Bounded world simulation, its events, decisions and permitted effects through existing host application paths. | Preserve leases, clocks, timeline/source rules and the [CHPM compatibility gates](../living-world-usage.md). A background controller has no unrestricted write permission. |
| [Memory and World Info](../session-world-info.md) | Scoped knowledge records, publication, provenance, retrieval and derived indexes. See [RAG](../memory-rag.md). | A recalled claim, rumor or subjective note does not overwrite current ownership, location or conditions. Retrieval is not a world action. |
| [Narration](narrative-stage-boundaries.md) and [portrait cues](../npc-portrait-presentation.md) | Prose candidates, source-bound expression and independently validated display emotion/thought metadata. | NPC meaning review and physical reconciliation are different checks. Display cues and speech delivery do not write private psychology or game state. |
| [Images and illustrations](../portrait-regeneration.md) | Visual context preparation, provider execution, owned jobs/artifacts and image associations. [Story moments](../comfyui/README.md#moment-illustrations) use their existing snapshot contract. | Image output cannot transfer items, change clothing state, heal a condition or publish an NPC decision. Asset metadata is not gameplay authority. |
| Speech | Provider-specific [synthesis](../../backend/engine/tts_engine.py) and [recognition](../../backend/api/routes/stt_api.py) through their existing paths. | Recognized text enters the ordinary authorized input path. An audio provider does not directly execute a game action. |
| [Authoring and portability](../specs/adventure_format.md) | Adventure creation/editing, validated import/export and the applicable session/archive lifecycle. | Preserve identities, supported formats, attribution and scoped runtime state. Carrying an extension is not permission to activate an unwired adapter. |
| [Recovery and checkpoints](../session-checkpoints.md) | Existing turn receipts, recovery snapshots, replay, copy/restore and derived-state invalidation. | Other subsystems preserve these fences. Each owner declares retention semantics; private notebooks intentionally retain their latest content across story rewind. |
| [Inference](../inference-queue.md), [configuration](../llm-sampling.md) and [diagnostics](system-diagnostics.md) | Shared role routing, admission, budgets, settings and observable execution outcomes. | A local feature must not silently rewrite shared provider settings, bypass applicable queue admission or expose private prompts in ordinary logs. |

## 3. Contract required at an integration

A contract can be an existing typed function, Pydantic model, protocol, operation
or event structure. Reuse the current contract and validators. Do not create a
parallel schema or state store merely to satisfy this document.

For a changed boundary, its implementation and documentation must establish:

1. **Owner and consumers:** who validates/publishes the result, who reads it and
   which entry points exist, including disabled features and fallback paths.
2. **Input and audience:** required IDs, scope, source identity/revision/hash,
   freshness, accessible fields, unknown values and limits.
3. **Output and permitted effects:** the result shape, which owner may apply it,
   and whether the operation reads, proposes, mutates or schedules work.
4. **Failure:** distinguish rejected, unavailable, incomplete, explicitly empty
   and already committed outcomes. Define what is retained and what the caller
   can safely retry; never replay an uncertain mutation as a fresh action.
5. **Resources:** role/model selection, deadlines, input/output sizes, quotas,
   request/retry limits, cancellation and queue priority. Shared limits must agree
   between producers, validators, persistence and consumers.
6. **Lifecycle and compatibility:** initialization, reload, source edits,
   regeneration, replay, copy, import/export, deletion and checkpoint restoration
   where applicable. Public module releases and saved/wire schema versions serve
   different purposes; follow the existing version policy in [AGENTS.md](../../AGENTS.md).
7. **Evidence:** named tests for the boundary and affected consumers. State what
   mocked/schema checks establish separately from live-model quality or latency.

## 4. Allowed communication and persistence

- Routes call domain operations. Domain code must not import route implementations,
  even lazily; retain existing compatibility facades without putting new logic in them.
- Read projections are prepared through existing owners. Do not pass unrelated
  private records simply because they are reachable from the same session object.
- Mutations use the existing domain validation/application paths. Do not patch
  another subsystem's JSON namespace or SQL rows from a renderer, tool adapter,
  prompt builder, UI component or unrelated worker.
- The coordinator controls ordering and retains the current leases, revisions,
  receipts and recovery behavior. Do not hold a new long SQL write transaction
  across model/GPU waits or assume the whole turn already has one atomic commit.
- Background work declares its effects. Indexing and rendering update their own
  artifacts; legitimate world simulation still uses its world mutation owners.
  Recheck ownership, source freshness and applicable revision/epoch fences after awaits.
- A supported local failure preserves the relevant previously valid facts.
  Independent valid effects may survive a rejected delta. This is not a promise
  that every domain is rolled back, or that a late refusal rewrites earlier prose.

## 5. Example: changing image generation

The intended dependency direction is:

`canonical owners → permitted visual view/snapshot → prompt/workflow → provider → owned artifact`

The preparation layer selects current appearance or a historical story moment
according to its existing contract. The generator consumes those prepared facts;
it does not independently repair the world to match a prompt or generated pixels.

For a local sampler, checkpoint adapter, prompt-format or reference-workflow change:

- Retain task/profile selection, source/audience rules, frame identity and input
  limits. Keep the original item and character IDs.
- Return through existing image/job persistence. An image association, artifact,
  provenance record or job status is an allowed visual effect; possession,
  clothing, physical conditions, relationships and clocks are outside that effect.
- Retain existing failure, cancellation and stale-result behavior, including
  preservation of the prior image where the existing path promises it.
- Use the applicable existing routing, admission and job controls. Model-backed
  prompt preparation uses text-role budgets; ComfyUI has its own provider queue
  and is outside current text/embedding admission. Extending coordination across
  these paths changes a shared contract. Do not compensate for a bad image by
  changing shared NPC/narrator configuration or adding undisclosed retries.
- Verify task/reference selection, ownership and stale-source rejection, failure
  preservation and relevant image consumers. Extend an existing integration test
  when the changed behavior crosses that seam.

Changing the visual input contract itself requires updating its producer and
consumers together. Changing shared routing/queue/storage requires checking their
other users too. Isolation limits the affected area; it does not prove zero
performance or integration effects.

## 6. Change and review discipline

Before implementation, name the changed owner and trace its producers, validators,
persistence and consumers. Prefer a change inside that owner with the existing
contract. If the contract must change, describe the change explicitly and update
both sides, compatibility handling and documentation in the same coherent work.
This is a review requirement, not an additional user-approval step.

For each change, record the following in the implementation notes or PR:

- **Scope:** owner/path, entry points and permitted effects.
- **Contract impact:** unchanged, compatible extension or incompatible change;
  list the affected fields, limits and consumers when it changes.
- **Failure/lifecycle impact:** retained facts, receipts, retries and applicable
  source/replay/import/export behavior.
- **Verification:** meaningful owner tests and affected consumer combinations,
  including disabled/fallback paths. Preserve existing assertions and budgets.
- **Known limits:** shared dependencies or legacy coupling that remain relevant;
  do not report a documented rule as already enforced by a universal runtime guard.

Existing [engine layering tests](../../tests/test_engine_layering.py) check
`from backend.api...` imports in engine code and compatibility-facade identity.
They do not constitute a complete dependency graph or prove absence of every
possible dynamic import or cross-domain mutation. Existing domain suites provide
additional behavioral checks; select and extend those appropriate to the change.
Do not add tests that merely look for policy wording in Markdown.

The standard is enforced through contributor/agent instructions, review and the
specific automated boundaries already present. Stronger automated checks should
be added incrementally for a demonstrated seam, with a regression and explicit
legacy handling, rather than claiming the whole monolith is already isolated.
