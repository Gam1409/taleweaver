# LLM context and turn pipeline

This is an architecture reference for the current fork. Prompt layouts and request
counts depend on the game mode, enabled modules, provider output policy and retry
path; they are not one universal three-call protocol.

The orchestration owner is
[`GameTurnManager`](../../backend/engine/gameplay/manager.py). See the
[sequence diagram](../diagrams/game_session_loop.mermaid) and
[activity diagram](../diagrams/game_session_loop_activity.mermaid) for the main
paths. Commands, combat, terminal reports and narration-only regeneration have
their own branches.

## Mode-dependent resolution

The authoritative mode policy is
[`game_modes.py`](../../backend/core/game_modes.py). The usual paths are:

| Mode | Resolution before prose |
| --- | --- |
| RPG | Structured mechanics, deterministic access/skill/combat handling and host validation. |
| Story | Structured streamlined mechanics and progression; not RPG turn-based combat. |
| Chat | Ordinary narration, with applicable host rules and optional generator tools. |
| Visual Novel (`vn`) | Structured VN progression, access, movement, time and continuity; no RPG combat, XP, quests or awards. Optional NPC Personality runs before narration. |

The legacy `strict_rules` flag can override mechanics selection in non-VN modes;
it cannot enable RPG mechanics inside VN. Do not infer a request path solely from
a display label or assume Chat always sends a mechanics request.

Mechanics output is parsed using the current request schema (for example,
`MechanicsIntent`), validated and converted to the engine's `GameEvent` where
needed. The internal `GameEvent` is not a universal direct LLM wire schema.
Structured transport may use native schemas, JSON compatibility or prompt-only
output; [local validation remains authoritative](../structured-output.md).

## Context owners

The turn context combines several projections. These projections serve different
audiences and are not a dump of every database row.

| Context | Owner and meaning |
| --- | --- |
| Player identity and mechanical sheet | Session avatar, equipment and the active mode's sheet projection. |
| Scene and routes | Current scene, session overrides, discovered/access-checked objects and exits. |
| Narrative frame | The session's adventure snapshot, selected tone, narrator style/amount/flow, language and saved history window. |
| Inventory and clothing | Existing possession and clothing projections with canonical item IDs, current owners and known wear/coverage. |
| Physical conditions | Source-bound canonical condition records; missing state is unknown rather than a clean bill of health. |
| Recall | Bounded [memory retrieval](../memory-rag.md) with source and audience checks. Retrieved text is data, not an instruction layer. |
| World Info | Accepted [session-owned entries](../session-world-info.md); a blueprint or corpus reference does not automatically become live session memory. |
| NPC cognition | Observer-specific host facts, accessible evidence, authored identity and optional personal tools. Another NPC's private state is not shared context. |
| Visual context | The existing appearance, condition and scene projections used to capture a selected story moment. |

An off-scene identity reference does not establish that an NPC is visible,
reachable or available for an interaction. Hidden contents are not made public
by placing a container or its owner in the scene. Each consumer retains its own
visibility, ownership and source checks.

History selection and context budgets can omit facts. Explicit omission counts,
unavailable sources and failed lookups never establish that a thing is absent or
that a replacement identity should be created.

## Host validation before narration

Technical models propose effects; the host resolves them using the existing
domain owners. Relevant checks include exit/container requirements, switch
transitions, canonical possession, portable/fixed-item behavior, scene scope,
visibility, known IDs and deterministic guards.

The host does not enforce item access by matching a display name against the
player's sentence. It validates the proposed state transition and any required
source/intent evidence. Illegal effects are rejected or reverted, and resolution
or refusal information reaches narration.

The older name **Pass 1.5** describes these server-side checks. It is not an extra
model or a guarantee that every state owner is updated.

## NPC meaning and optional tools

NPC Personality selects bounded message meaning for its controlled NPCs.
[Staged and Integrated workflows](../npc-decision-workflows.md) share the same
source, budget, autonomy and review boundaries. Shadow results do not steer
ordinary narration; disabled mode adds no cognition request.

Existing optional tool rounds can read memory, beliefs, the observer's own facts,
visible clothing and [current observable entity state](../npc-observable-state.md).
Notebook tools are separately enabled and operate on one NPC's private JSON
document. Reads do not perform a world action or reserve an item. A private note
does not become an objective world fact.

The narrator receives accepted meaning plans and host outcomes. Shared review can
require repair or reject an inconsistent response. Failed or locally deferred
NPCs use the existing fallback/partial-turn policy; a plan alone is not published
biography, possession or history. See
[narrative ownership boundaries](../engineering/narrative-stage-boundaries.md).

## Narration, reconciliation and publication

Narration expresses the validated outcome using the selected language,
presentation and formatting. Failure instructions prevent prose from replacing
a denied action with an apparent success. Literary wording remains model output;
host checks and live quality evaluation address different questions.

For completed VN narration, the existing shared extractor checks supported item,
clothing, physical-condition and continuity proposals against current canonical
state and exact source evidence. Optional scene staging has its own bounded
reconciliation. Independent valid facts can survive an unrelated rejected delta;
unknown or ambiguous evidence does not justify inventing an update.

The completed reply is persisted before its ID can anchor source-bound memories
and frozen illustration records. NPC publication, source binding, derived-index
invalidation and the final turn commit follow their existing owners. Memory
maintenance, journals and eligible visual work can be scheduled after publication.
They do not gain permission to advance the foreground turn.

Ordinary unbuffered narration sends prose chunks while the model generates them,
before reconciliation and commit. Live CHPM buffers prose when a turn has
decisions or simplified review: the reviewed reply is delivered after the commit,
immediately before the final receipt. Status and intermediate state events can
still arrive earlier.

SSE `status`, text and intermediate `state` events expose progress. They are not
the final commit receipt. The client uses the final response and history recovery
path to reconcile an interrupted stream instead of replaying an uncertain action.

## Time, audio and visual side paths

Base in-game turn boundaries follow scene/sequence changes. VN also has bounded
within-scene elapsed-time and explicit time-passage handling; a normal message
must not be confused with one fixed clock increment. See
[VN time passages](../vn-time-passages.md). Playtime is a separate heartbeat.

Portrait presentation, illustration rendering and speech use their own settings
and data owners. Delivery cues retained in narration/history are not disposable
technical JSON. The audio provider prepares speech using its supported voice and
delivery controls; there is no universal instruction to strip every cue from all
story text. An image or thought bubble never commits an inventory or mind change.

For rewriting only the latest prose, use
[narration regeneration](../engineering/narration-regeneration.md).
Full-turn replay and Chronicles restoration are separate operations.
