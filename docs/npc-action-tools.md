# NPC action tools: implementation status

The action interface is experimental and disabled by default. Offline checks
verify engine contracts; live-model comprehension and reliability still need
matched live evaluation.

## Current command path

The backend `action_tools` setting requires live NPC Personality, the integrated
workflow and at least one agent round. Legacy settings load with `false`; off,
shadow and the original staged workflow keep their existing behavior. Enable it
in **Session settings → NPC Personality → Action tools**. Enabling actions selects
Integrated and at least one tool round without enabling private notebooks.
Adventure defaults apply only when creating a session.

The host derives the control scope from the actual game mode. VN uses `dialogue`,
with the full existing psychology and narration review. RPG uses `combat_actions`
for authored ability choices during actual combat initiative. It does not run VN
psychology or suppress Living World dialogue controllers. RPG exposes Standard
and Enabled; Observe remains a VN feature. Chat does not offer this controller.

The implemented commands are `take_item`, `put_down_item`, `give_item`,
`wear_item`, `take_off_item`, `adjust_clothing`, `change_item_state`, `use_item`,
`move_to`, `set_pose`, `approach`, `interact`, and `discard_actions`.
Existing `find_entity`, `inspect_self`, `inspect_entity` and `inspect_scene`
supply scoped current identifiers and facts.
Functions are offered from the available scene/possession capabilities. A function
being offered is not proof that every possible argument or target is allowed.

`use_item` currently records qualitative partial/full use on the same object. It
does not grant mechanical effects, guess numerical quantities, consume combat
resources or delete a reusable object's identity. Actual RPG consumption and
abilities must use the existing resource and combat owners.

`set_pose` records the NPC's own final posture, including `on_all_fours`.
`approach` records a local relation to an accessible actor or loose scene object;
walk/run finish standing and crawl finishes on all fours. It does not change rooms
or calculate distances, collision geometry or a movement animation. Action opt-in
enables the existing optional scene staging owner in VN. Turning actions off does
not erase staging or disable a separately useful presentation feature.

`interact` submits only the actor's own attempted action, toward an accessible
actor, object or self. Its publication status is `attempted`, never `applied`.
Recipient cooperation, bodily consequences and mechanical success remain
unresolved until their existing owners have sufficient evidence. There is no
arbitrary recipient-state setter or separate permission tool.

## State ownership and publication

1. Before inference, the host captures transient working copies of canonical
   possessions, wardrobe facts, condition and pose state, and permitted routes.
   The actor, session, scene and input are host-bound, not function arguments.
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
5. Changes go through the existing item, clothing, condition, staging and movement
   owners.
   The enclosing recoverable turn owns the transaction and game clock; individual
   commands do not create extra player turns. Room travel ends the source-scene
   plan rather than granting destination-room observations from an old view.
6. Narration state and portrait cast are refreshed after applied commands. The
   narrator receives authoritative applied/attempted/blocked/stale/skipped
   outcomes, with earlier observations identified as preceding publication.
7. Shared extraction cannot repeat or reverse command-owned inventory, wardrobe
   and travel effects. Only handled item-property dimensions are protected;
   independent body conditions, other dimensions and unrelated scene effects
   remain eligible for normal evidence-backed extraction. Pose protection covers
   only the command's explicit final posture/placement, including explicit clears.
   Unrelated staging facts remain eligible for normal extraction.

Command property provenance is explicitly `command`, anchored to the saved input
with a host-issued operation identity and request hash. It is never labeled as
an invented narrated quotation. Existing condition IDs are reused for later
changes to the same active dimension. Descriptive properties cannot replace
identity, custody, wardrobe, character state or mechanical fields.

Command wear provenance separately binds the saved input's content hash and
revision, plus the operation request hash. Copy/remapping retains those real
anchors. Narrator and equipment-card projections recognize a confirmed command
placement even when displacement leaves no covered garment surface. Unknown wear
is never silently treated as confirmed carried clothing.

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

## Authored abilities in VN

The bound NPC receives its own current card description and authored ability
names/descriptions, including magic described only in prose. The existing pinned
character, goals and traits stay separate and are not replaced. This transient
self-knowledge is not a witnessed event, proof of success or a mechanical effect.
It adds no model request and changes no persisted psychological schema.

The view fits 6,000 serialized characters: at most eight ability descriptions,
with explicit truncation and omission counts. Narrative-only abilities need no
invented combat ID. Raw scripts, guards, numerical effects and nested metadata
are excluded. The NPC does not receive another character's or the protagonist's
private ability catalog; knowledge about them still needs existing observable
or reported sources. VN can use authored magic for a narrative intention without
activating the RPG combat driver.

## RPG ability choices

RPG offers only `use_ability(ability_id, target_id)` and `keep_default()` during
the selected NPC's actual initiative. The bounded context contains that NPC's
authored identity and abilities, available targets and current resources. Private
minds, scripts and other inventories are excluded. The current owner supports
its established self/player targeting; this interface does not create party-wide
targeting or new abilities.

The existing combat driver validates the encounter frame, available resources,
costs, hits, scripts and casualties. A choice cannot create an extra turn or bypass
ability rules. `keep_default` explicitly delegates to baseline AI; it is not a
wait action. No authored ability means no selection request. Uncertain transport
failure is not retried as a potentially duplicated command.

Combat request admission reserves selected active NPCs × configured rounds.
It does not add VN perception/reviewer reservations. The controller requires the
existing recoverable command turn, and cancellation/retry use that owner. Timings
and call usage use the existing diagnostics, without a separate event ledger.

## Validation

Offline checks cover strict argument parsing and scope binding, copy-on-write
previews, conflicting acquisitions, ordered transfers, property identity,
save/reload, visibility, recovery/Undo, and the real integrated turn through both
native and JSON ports. Mocked model responses establish engine behavior, not
small-model comprehension, emotional quality or live reliability.

Further checks cover local pose/approach, attempted interactions, exact command
provenance, native/JSON schema references, host-derived mode scope, controller
switches and initiative/resource/recovery boundaries. The independent live-test
plan and raw results stay outside the repository. Offline scripted results do
not establish that a live model chooses sensible actions or uses tools reliably.

Related: [subsystem contracts](engineering/subsystem-contracts.md),
[observable state](npc-observable-state.md),
[tool-calling research](research/npc-tool-calling.md),
[Harness² assessment](research/harness2-for-npc-tools.md).
