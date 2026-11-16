# Documentation

Use this index for the current source checkout. The [project overview](../README.md)
contains installation entry points and a feature summary. The
[GitHub Wiki](https://github.com/Gam1409/taleweaver/wiki) is a generated reading view;
[Wiki synchronization](wiki.md) describes how it is built from a reviewed commit.

## Start here

| Goal | Guide |
| --- | --- |
| Install or update | [Quick start](../README.md#-get-started), [desktop](desktop.md), [Docker storage](docker-storage.md) |
| Configure models | [OpenAI-compatible APIs](custom-openai-compatible.md), [Ollama](ollama-roles.md), [routing and deadlines](llm-sampling.md) |
| Start playing | [VN mode](visual-novel-mode.md), [content language](session-content-language.md), [player tools](player-tools.md) |
| Add NPC decisions | [Player controls](chpm-continuation.md), [workflows](npc-decision-workflows.md), [state tools](npc-observable-state.md), [notebooks](npc-notebook.md) |
| Import session knowledge | [World Info](session-world-info.md), [memory retrieval](memory-rag.md) |
| Create or exchange worlds | [World blueprints](world-blueprints.md), [staged generation](staged-world-generation.md), [catalog](adventure-catalog.md), [formats](specs/adventure_format.md) |
| Configure pictures | [ComfyUI](comfyui/README.md), [task templates](comfyui-task-templates.md), [portraits](portrait-regeneration.md) |
| Diagnose a turn | [Debug controls](in_game_debugging.md), [state consistency](turn-consistency.md), [timing](turn-latency.md), [system diagnostics](engineering/system-diagnostics.md) |
| Understand a complete turn | [Scene, items, conditions and emotions, with and without NPC Personality](engineering/turn-lifecycle.md) |

### Which version does a page describe?

Current guides follow the source checkout. Release archives contain their tagged
code: a matching application version string does not mean an older binary includes
later commits from main. Release notes preserve the features and results of their
own tag. Research, design plans, audits and evaluations carry scope/status notes;
their measurements and proposed work are evidence from that snapshot.

| Layer | Reference |
| --- | --- |
| Application release | [version.json](../version.json): 0.7.1-beta |
| NPC Personality module | [public module version](../backend/engine/chpm/version.py): 1.2.0, independent of the app and saved-state schemas |
| Adventure export format | [format owner](../backend/core/adventure_format.py): 1.3; the [catalog adapter](adventure-catalog.md) admits checked records through 1.3.1 |
| Portable agent configuration | [contract v1](specs/agent_runtime.md): authored schemas/transport/negotiation; activation adapters and remote corpus ingestion remain separate integration work |
| Saved subsystem schemas | Owned by their runtime modules; see [CHPM lifecycle](chpm-memory-lifecycle.md), [memory](memory-rag.md) and [checkpoint behavior](session-checkpoints.md) |

Optional model-backed features have their own gates and limits. Passing schema or
mocked integration tests establishes host behavior; live-model quality and latency
depend on the selected model, provider, context and workflow.

## Players and sessions

Current gameplay, continuity and recovery guides.

- [Chat scene transitions](chat-scene-transitions.md)
- [Debug transcript and story context](debug-history-scope.md)
- [Dynamic local exploration (experimental)](dynamic-locations.md)
- [Refreshing action ideas](idea-refresh.md)
- [Interrupted answers and retry](interrupted-turns.md)
- [Repair an existing session item](item-repair.md)
- [Current item state](item-state.md)
- [Completed narration and possessions](narrated-item-reconciliation.md)
- [Completed narration and canonical travel](narrated-movement.md)
- [Narrator corrections](narrator-corrections.md)
- [Narrator style](narrator-styles.md)
- [Persistent physical state](persistent-physical-state.md)
- [Repair and retry actions](repair-and-retry.md)
- [Scene continuity](scene-continuity.md)
- [Scene reliability and recovery](scene-reliability.md)
- [Experimental scene pose and placement continuity](scene-staging.md)
- [Session checkpoints](session-checkpoints.md)
- [Session content language (experimental)](session-content-language.md)
- [Content preferences in an existing session](session-content-settings.md)
- [Storage identifiers and multilingual names](storage-identifiers.md)
- [Turn consistency and manual recovery](turn-consistency.md)
- [Regenerating the latest turn](turn-regeneration.md)
- [Visual Novel mode](visual-novel-mode.md)
- [VN story initiative](vn-story-initiative.md)
- [Explicit VN time passages](vn-time-passages.md)
- [Correcting NPC clothing and item placement](wardrobe-debug-recovery.md)

## NPC memory and world

NPC controls, implementation references and maintained module history. Dated evaluations are listed under research and history.

- [Optional bounded CHPM agent](chpm-agent.md)
- [CHPM qualitative appraisal stage](chpm-appraisal.md)
- [NPC Personality 1.1.0: causal continuity](chpm-causal-memory.md)
- [NPC Personality release history](chpm-changelog.md)
- [Keep playing when NPC analysis fails](chpm-continuation.md)
- [Slow developmental reflections](chpm-development.md)
- [Source-bound affect and need appraisals](chpm-experience.md)
- [Larger VN casts](chpm-large-casts.md)
- [CHPM history, capacity and subjective memory](chpm-memory-lifecycle.md)
- [Source-bound decision motives](chpm-motivation.md)
- [NPC Personality — optional CHPM intentions module](chpm-pilot.md)
- [Semantic NPC memory](chpm-semantic-memory.md)
- [Historical source recovery and NPC reports](chpm-source-continuity.md)
- [CHPM observer-local world perception](chpm-world-perception.md)
- [Bounded memory working set](engineering/memory-working-set.md)
- [NPC memory consolidation: assessment and first implementation wave](engineering/npc-memory-consolidation.md)
- [NPC presence](engineering/npc-presence.md)
- [Living World architecture](living-world-architecture.md)
- [Living World · Experimental](living-world-usage.md)
- [Memory and relevant recall](memory-rag.md)
- [NPC action autonomy](npc-action-autonomy.md)
- [NPC decision workflows](npc-decision-workflows.md)
- [Characters introduced during play](npc-introductions.md)
- [Private NPC notebooks](npc-notebook.md)
- [NPC observable state tools](npc-observable-state.md)
- [World features: current foundations and remaining work](planned-world-features.md)
- [Player input and character history](player-tools.md)
- [Session World Info](session-world-info.md)

## Images and workflows

Current image setup and visual-state contracts. Screenshot galleries and examples retain the scope stated on their own pages.

- [Local Stable Diffusion with Automatic1111 / Forge](HOWTO_LOCAL_STABLE_DIFFUSION.md)
- [TaleWeaver Screenshot Gallery & Explanations](SCREENSHOTS.md)
- [ComfyUI task preset templates](comfyui-task-templates.md)
- [ComfyUI image generation](comfyui/README.md)
- [Generation presets and prompt templates](comfyui/presets.md)
- [Starter workflows and validation](comfyui/starters.md)
- [Visual prompt fidelity](diagnostics/visual-fidelity.md)
- [NPC portrait presentation](npc-portrait-presentation.md)
- [Portrait composition and regeneration](portrait-regeneration.md)
- [Bundled font-file and license index](../frontend/public/assets/fonts/licenses/README.txt)
- [Session fonts](../frontend/public/assets/fonts/session/README.md)

## Authoring and formats

World creation, import/export contracts, public-copy preparation and actual scripting behavior.

- [Adventure authoring validation and completion](adventure-authoring-validation.md)
- [Adventure catalog and original-project exports](adventure-catalog.md)
- [AI-Fix provider policy](ai-fix-providers.md)
- [Create an NPC from a description](editor-npc-creation.md)
- [Post-generation validation and auto-fix](post-generation-auto-fix.md)
- [TaleWeaver Scripting Engine Guide](scripting_engine.md)
- [TaleWeaver adventure format](specs/adventure_format.md)
- [Portable agent runtime contract, version 1](specs/agent_runtime.md)
- [TaleWeaver Entity Bundle (.twe)](specs/entity_bundle_format.md)
- [LLM context and turn pipeline](specs/llm_injection_spec.md)
- [Staged world generation](staged-world-generation.md)
- [World blueprints and open-ended author briefs](world-blueprints.md)
- [World-builder syntax](world-builder-syntax.md)

## Installation and providers

Environment, storage, routing, inference admission and operator diagnostics.

- [Self-hosted OpenAI-compatible inference](custom-openai-compatible.md)
- [DeepSeek connection and output modes](deepseek.md)
- [Dependency security checks](dependency-security.md)
- [Desktop applications](desktop.md)
- [Docker storage](docker-storage.md)
- [Database and legacy utility entrypoints](engineering/database-entrypoints.md)
- [System diagnostics](engineering/system-diagnostics.md)
- [In-Game Debugging Guide](in_game_debugging.md)
- [Experimental shared inference queue](inference-queue.md)
- [Parallel requests by LLM role](llm-parallel-requests.md)
- [Generation settings and sampling](llm-sampling.md)
- [Independent Ollama settings for LLM roles](ollama-roles.md)
- [Provider network policy](provider-network-policy.md)
- [Technical structured output](structured-output.md)
- [Understanding turn latency](turn-latency.md)

## Engineering

Source boundaries, diagrams, maintainer policies and documentation tooling.

- [Copilot Instructions](../.github/copilot-instructions.md)
- [TaleWeaver Agent Guidelines](../AGENTS.md)
- [Assets and attribution](../ASSETS.md)
- [Desktop artwork](../desktop/assets/README.md)
- [adventure export](diagrams/adventure_export.mermaid)
- [adventure generation](diagrams/adventure_generation.mermaid)
- [adventure generation activity](diagrams/adventure_generation_activity.mermaid)
- [adventure import](diagrams/adventure_import.mermaid)
- [game session loop](diagrams/game_session_loop.mermaid)
- [game session loop activity](diagrams/game_session_loop_activity.mermaid)
- [Turn services and the API boundary](engineering/engine-boundary.md)
- [Subsystem responsibilities and contracts](engineering/subsystem-contracts.md)
- [Complete turn lifecycle: scene, state and NPC decisions](engineering/turn-lifecycle.md)
- [Frontend request and stream contracts](engineering/frontend-transport.md)
- [Narration flow guidance](engineering/narration-flow.md)
- [Regenerating the latest narration](engineering/narration-regeneration.md)
- [Narrative stage boundaries](engineering/narrative-stage-boundaries.md)
- [GitHub Wiki synchronization](wiki.md)

## Research and history

Plans, original research, dated audits, experiment reports and release announcements. Read their status notes before applying historical commands or conclusions to current code.

- [TaleWeaver v0.6.0-beta: The Immersive In-Game & Scripting Engine Release](../RELEASE_NOTES_v0.6.0-beta.md)
- [TaleWeaver · Visual Novel Fork](../RELEASE_NOTES_v0.7.0-beta.md)
- [TaleWeaver v0.7.1-beta](../RELEASE_NOTES_v0.7.1-beta.md)
- [Character appearance and clothing](character-appearance-and-clothing-plan.md)
- [Emotional progression evaluation](chpm-emotional-evaluation.md)
- [CHPM dialogue comparison and stress testing](chpm-evaluation.md)
- [Final pilot validation before merge](chpm-final-validation.md)
- [Cast and history evaluation matrix](chpm-matrix-evaluation.md)
- [NPC analysis performance](chpm-performance.md)
- [CHPM research implementation map](chpm-research-roadmap.md)
- [Clothing integration audit](clothing-audit.md)
- [Default ComfyUI workflow validation](comfyui-default-validation.md)
- [ComfyUI setup review](comfyui/ux-review.md)
- [Historical ComfyUI validation records](comfyui/validation-history.md)
- [Multilingual visual contracts — round 2](design/multilingual-visual-contract-round2.md)
- [Multilingual visual contracts across tags, prose and hybrid prompts](design/multilingual-visual-contract.md)
- [NSFW required atoms (Stage 3)](design/nsfw-required-atoms-stage3.md)
- [Saved visual plans: Stage 1 implementation](design/visual-plan-stage1-implementation.md)
- [Shared visual plans and default scene preparation](design/visual-plan-stage2-implementation.md)
- [CI checks and historical failure audit](engineering/ci-audit.md)
- [Persistence and concurrency audit](engineering/concurrency-audit.md)
- [Situation, personality and emotion: research and implementation plan](engineering/emotion-context-research-plan.md)
- [Emotional progression: matched-case specification](engineering/emotional-progression-cases.md)
- [NPC Personality: emotional progression and expression](engineering/emotional-progression-issue-33.md)
- [Emotional progression: evidence and engineering decisions](engineering/emotional-progression-research.md)
- [Emotional scene continuity probe — 2026-11-10](engineering/emotional-scene-test-2026-11-10.md)
- [Review remediation: experimental Living World branch](engineering/review-remediation-2026-10.md)
- [Session integrity review repairs](engineering/review-repairs-2026-11.md)
- [RP engine scenario matrix](engineering/rp-adversarial-scenario-matrix.md)
- [Backend refactoring and CI lint cleanup](engineering/ruff-refactor.md)
- [Structured output: live validation boundaries](engineering/structured-output-live-review-2026-11-10.md)
- [Neutral visual quality experiment](experiments/neutral-visual-quality.md)
- [Ollama role implementation report](ollama-roles-report.md)
- [RAG audit and implemented corrections](rag-audit-2026-11.md)
- [Original CHPM research document (immutable source, Russian)](research/chpm/CHPM_Research_Architecture_v0_2_RU.md)
- [CHPM research sources](research/chpm/README.md)
- [compact-prompt.txt](research/rp-state-eval-2026-11-07/compact-prompt.txt)
- [RP state reconciliation: investigation and free-endpoint pilot](research/rp-state-reconciliation-2026-11-07.md)
- [Interface parity review](reviews/interface-parity.md)

## Supporting artifacts

- [Branding and screenshots](SCREENSHOTS.md) link the checked-in images; their
  existence is not a claim that screenshots match every later interface revision.
- [Runtime JSON Schemas and ADV examples](specs/agent_runtime.md#files-and-verification)
  belong to the portable authoring contract. ComfyUI examples include
  [SDXL text](comfyui/sdxl-text-api.json), [SDXL reference](comfyui/sdxl-image-api.json)
  and [FLUX.1 FP8 text](comfyui/flux1-fp8-text-api.json) workflows.
- [Research provenance](research/chpm/README.md) records hashes for the original
  paper and matrix. Preserve those source bytes. JSON/JSONL experiment results
  remain scoped to their adjacent report; they are not live provider configuration.
- [Assets and attribution](../ASSETS.md), the root [code](../LICENSE) and
  [story-content](../LICENSE-CC-BY-NC-4.0) licenses, and bundled third-party notices
  retain their own licensing scope.

## Keeping guides current

1. Trace behavior to its existing source owner, UI control and test before changing
   a claim. Distinguish stored state, derived views and model proposals.
2. Keep enablement gates, defaults, limits, languages and examples aligned across
   producer, consumer and persistence paths. Link the detailed owner guide rather
   than copying a long settings table into every overview.
3. Describe implementation, opt-in features and future integration explicitly.
   Preserve dated research and evaluation results as historical evidence.
4. Check relative files, heading anchors, command flags, JSON examples and Mermaid
   syntax. Use the project environment for CLI commands; private agent tooling is
   optional. Model-backed examples require explicit live-test setup.
5. Preserve legal notices and original research attachments. Use neutral examples;
   exclude credentials, private endpoints, raw sessions and temporary preview URLs.
6. Update this index and regenerate the Wiki from the same reviewed commit using
   the [Wiki guide](wiki.md). Generated Wiki pages are not a second hand-edited source.
