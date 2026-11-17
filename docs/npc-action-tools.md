# NPC action tools: implementation status

The action interface is experimental and disabled by default. This document
describes the implemented foundation; it does not claim that the complete planned
action surface or live-model evaluation is finished.

## Current command path

The backend `action_tools` setting requires live NPC Personality, the integrated
workflow and at least one agent round. Legacy settings load with `false`; off,
shadow and the original staged workflow keep their existing behavior. The current
NPC Personality host is Visual Novel only. The owner-facing action control and
the broader pose, interaction and RPG integration are subsequent work.

The implemented commands are `take_item`, `put_down_item`, `give_item`,
`wear_item`, `take_off_item`, `adjust_clothing`, `change_item_state`, `use_item`,
`move_to`, and `discard_actions`. Existing `find_entity`, `inspect_self`,
`inspect_entity` and `inspect_scene` supply scoped current identifiers and facts.
Functions are offered from the available scene/possession capabilities. A function
being offered is not proof that every possible argument or target is allowed.

`use_item` currently records qualitative partial/full use on the same object. It
does not grant mechanical effects, guess numerical quantities, consume combat
resources or delete a reusable object's identity. Actual RPG consumption and
abilities must use the existing resource and combat owners.

## State ownership and publication

1. Before inference, the host captures transient working copies of canonical
   possessions, wardrobe facts, condition state and permitted routes. The actor,
   session, scene and input are host-bound, not function arguments.
2. Calls validate and stage an ordered plan. Tool results explicitly say
   `world_changed=false`. Reads continue to describe the canonical current world;
   the pending plan is separately marked as unperformed.
3. Successful final cognitive acceptance approves the pending plan. A rejected
   or unsubmitted decision cannot publish it. `discard_actions` abandons the plan
   without rolling back successful private notebook edits.
4. After all cognitive jobs finish, the host checks the actual saved input and
   controller settings, then publishes in stable NPC order. Each command rechecks
   current custody, presence, wardrobe prerequisites or movement permissions.
   A conflict blocks the later command and stops its dependent steps. It does not
   duplicate the item or imply that all earlier successful steps failed.
5. Changes go through the existing item, clothing, condition and movement owners.
   The enclosing recoverable turn owns the transaction and game clock; individual
   commands do not create extra player turns. Room travel ends the source-scene
   plan rather than granting destination-room observations from an old view.
6. Narration state and portrait cast are refreshed after applied commands. The
   narrator receives authoritative applied/blocked/stale/skipped outcomes, with
   earlier observations explicitly identified as preceding publication.
7. Shared extraction cannot repeat or reverse command-owned inventory, wardrobe
   and travel effects. Only handled item-property dimensions are protected;
   independent body conditions, other dimensions and unrelated scene effects
   remain eligible for normal evidence-backed extraction.

Command property provenance is explicitly `command`, anchored to the saved input
with a host-issued operation identity and request hash. It is never labeled as
an invented narrated quotation. Existing condition IDs are reused for later
changes to the same active dimension. Descriptive properties cannot replace
identity, custody, wardrobe, character state or mechanical fields.

Public command facts follow the existing visible clothing surfaces; covered or
private facts do not become public merely because an operation occurred. Legal
property ownership does not override physical custody or scene placement.

## Lifecycle and psychological boundaries

Plans are transient and are not loaded or replayed as executable data. Recent
duplicate publication on the same approved draft returns its existing results.
The existing recovery snapshot restores command effects after cancellation, and
Undo restores their canonical owner state. Session copies remap condition input
anchors; a missing source becomes explicitly unavailable while the saved fact
remains. Old source serialization omits the new absent command proof.

This interface does not provide an arbitrary physical or emotional state setter.
Internal appraisal, attempted emotional regulation and visible expression remain
distinct, owned by the existing psychology and presentation mechanisms. The NPC
chooses its own course; it cannot choose the player's thoughts, feelings or
voluntary response. An interaction attempt does not itself establish the other
participant's cooperation or a successful mechanical effect.

## Validation and remaining work

Offline checks cover strict argument parsing and scope binding, copy-on-write
previews, conflicting acquisitions, ordered transfers, property identity,
save/reload, visibility, recovery/Undo, and the real integrated turn through both
native and JSON ports. Mocked model responses establish engine behavior, not
small-model comprehension, emotional quality or live reliability.

Remaining work includes the expanded action surface, controller-safe RPG
integration, owner-facing controls, broader lifecycle combinations, a final
tool-calling review and live scenario verifiers. The independent live-test plan
and raw results stay outside the repository.

Related: [subsystem contracts](engineering/subsystem-contracts.md),
[observable state](npc-observable-state.md),
[tool-calling research](research/npc-tool-calling.md),
[Harness² assessment](research/harness2-for-npc-tools.md).
