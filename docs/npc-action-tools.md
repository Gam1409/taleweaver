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

The same [tool-calling profile](npc-tool-profiles.md) applies to VN action rounds
and RPG ability selection. Profile and native/JSON compatibility are independent
controls; neither grants new actions or changes their canonical publication rules.

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
   The command contract marks earlier observations and the host resolution as
   preceding publication. Review, repair and ordinary continuation also expose
   `host_resolution_time=before_command_publication`. Narration, review, bounded
   repair and ordinary continuation use the same command-owner instructions:
   applied commands supersede earlier conflicting results only for their exact
   owned fields. Earlier failures remain visible, including unrelated failures;
   attempted, blocked, stale, skipped or unconfirmed results establish no new
   successful effects. This timing label adds no request, world mutation or
   alternative state owner.
   A current approved plan with no commands retains an explicit empty result list
   for its actor. Narration, review, repair and ordinary continuation receive that
   same boundary: no voluntary command-owned change executed. An empty plan is
   neither a physical failed attempt nor an obligation to act; speech, waiting,
   refusal and no action remain valid. Unapproved previews and stale empty plans
   do not acquire this publication authority.
7. Shared extraction cannot repeat or reverse command-owned inventory, wardrobe
   and travel effects. Only handled item-property dimensions are protected;
   independent body conditions, other dimensions and unrelated scene effects
   remain eligible for normal evidence-backed extraction. Pose protection covers
   only the command's explicit final posture/placement, including explicit clears.
   Unrelated staging facts remain eligible for normal extraction.

A missing or failed staging extraction preserves still-valid earlier command
facts when the current cast is known. It keeps their original sources and does
not lock them against supported later changes. Scene, presence, position and
target checks still discard stale relations; no additional model request is used.

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
While live integrated dialogue action control is enabled, the earlier VN world
pass also checks direct portable-object placement proposals. It reuses the
optional movement source and the exact saved current-player passage; only a
resolved external player effect is eligible. Missing, stale, attempted or
intentional placements defer to the command and completed-narration owners,
preserving independent fields. Direct object travel additionally needs the
existing confirmed player traversal to that destination. Inventory transfers
retain their existing owner. These checks bind source identity and scope; the
model's classification of a physical effect remains fallible.
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
wait action. No available authored ability means no selection request. Uncertain transport
failure is not retried as a potentially duplicated command.

Combat admission applies the active NPC limit as eligible selected participants
reach their initiative turns. Absent NPCs and those without an available ability
do not consume a slot. An admitted NPC keeps its controller for subsequent turns
in the same command.

The request budget reserves **3 × selected active NPCs × configured rounds**.
Initiative rerolls can give an NPC two turns before the player's next turn;
resuming an unfinished enemy turn before the submitted player action can require
three. This reserve preserves all existing initiative turns and does not add
requests when fewer are needed. The call cap remains 25; configurations whose
reserve exceeds it require fewer active NPCs or rounds. VN perception/reviewer
reservations do not apply. Previously saved budgets remain readable and are not
raised automatically; an insufficient budget pauses combat selection before any
model request so the owner can explicitly update it in session settings.
The controller requires the existing recoverable
command turn, and cancellation/retry use that owner. Timings and call usage use
the existing diagnostics, without a separate event ledger.

## Validation

Each turn invocation has a host-issued attempt ID, including retries that reuse a
saved input. Tool operations and their results carry host-issued operation IDs;
feedback correlates those IDs instead of relying on result order. A staged action
retains its operation ID through publication and refers separately to its existing
canonical command proof. Closed, foreign or changed-input records cannot authorize
a current operation. An earlier invocation's cleanup cannot close a newer attempt.

Model-facing pending plans and feedback retain operation handles and domain
results, while complete input bindings and event metadata remain in host audit
records. Repeated hashes and command proofs do not consume the context again
for every staged step. This projection changes neither validation nor limits.

Preliminary failures retain their phase and input revision, so they remain distinct
from later applied commands in the same attempt. Refusal messages are rendered
from typed reason codes; legacy owner errors receive a generic code. Snapshot
fingerprints record before/after state for inspection and do not replace owner
precondition checks or provide a database compare-and-swap revision. Publication's
in-memory result cache is bounded to the active attempt. Item transfers have no
durable operation registry; this contract does not promise durable exactly-once
execution independently of the existing replay and rollback owners.

### Rejected command previews

The narrator, reviewer and existing prose repair also receive current
`rejected_command_previews` from the selected decision's tool audit, including
when every command was rejected and no publication plan exists. The projection
checks the attempt, input revision/hash, actor, operation and tool-call binding.
It exposes bounded action references and typed reason codes, excluding notebook
arguments, private purposes, free descriptions and diagnostic details. Invalid
arguments retain a typed rejection without inventing an item or target.

These records are preview feedback, not physical failed attempts or world facts.
Later applied publications supersede only the matching `superseded_fields`;
unrelated denials remain relevant. A rejected operation never becomes successful
retroactively. Valid refusal feedback does not abort the turn or require an
additional model request. Historical audits without operation bindings and older
hash-only summaries remain readable and gain no current control authority.
Rejection status (such as `blocked`) is distinct from its typed reason code
(such as `recipient_unavailable`). An unchanged cached decision's original audit
is retained history, never rebound to a new attempt or reissued as current feedback.

### Preliminary player operations

With live integrated dialogue action control enabled, VN progression proposes at
most six `player_item_actions` using canonical item/recipient IDs and the existing
saved `player:pN` source references. Each proposal requires an explicit
`performer_id`, separate from its recipient or clothing target. Only the supplied
player executor with `basis=performed` can authorize custody changes here. NPC
or explicitly unresolved performers remain deferred; omitting the performer
does not default to the player. The host binds execution to its player owner.
Final inventory, spawn, removal and deletion lists cannot independently authorize
custody changes. Requests for an NPC's voluntary actions remain pending until
that actor's action owner decides. Disabled, shadow and staged configurations
retain their existing progression contract.

Ordered player pickup, transfer, placement, theft and complete consumption/removal
are validated on canonical working possessions and applied by the existing world
owner. Saved source changes, a new attempt or changed custody invalidate the old
plan. Receipts retain parent operation IDs and report actual post-guardrail custody;
deferred proposals are distinct from failed actions. No additional model request
or executable proposal is persisted.

Fresh controlled-NPC wardrobe choices follow the same boundary. Player-performed
assistance requires a matching player operation, while the clothing owner retains
its consent, source, ownership, age, detail and coverage checks. Established-wear
initialization and completed-narration recovery keep their existing owners.
Independent condition changes remain outside the custody operation contract.

These checks establish legal operations and source identity. They do not prove
that a model correctly interpreted the performer or completion of arbitrary
natural-language input; that distinction still requires live evaluation.

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
