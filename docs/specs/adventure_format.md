# TaleWeaver adventure format

This reference describes authored adventure blueprints in the current fork.
The canonical writer is
[`AdventureExporter.build_full_manifest`](../../backend/engine/adventure_exporter.py).
The generated `WorldManifesto` and the simplified authoring/import DTO are related
inputs, not identical copies of this export envelope.

See [catalog compatibility](../adventure-catalog.md) for preparing an original-project
copy and [portable agent configuration](agent_runtime.md) for extension schemas.

## Files and versions

| Format | Contents |
| --- | --- |
| `.adv` | UTF-8 JSON adventure blueprint. Image references remain references. |
| `.adz` | ZIP with `adventure.adv` at its root and referenced local images below `assets/`. |
| `.ads` | A separate saved-session archive, including session state and history; not an adventure blueprint. |
| `.twe` | A separate [single-entity bundle](entity_bundle_format.md). |

The fork writes `format: "TaleWeaver"`, `version: "1.3"`. This top-level version
is the file-format version. `adventure.version` is the author's release version;
it is not replaced with the file-format number.

Ordinary imports require a supported envelope with a numeric version of at least
`1.0`. That minimum check is not a promise that every future upstream feature is
implemented. The community-catalog/public-copy adapter performs additional field
and script checks and currently audits envelopes through `1.3.1`; unsupported
APIs and newer envelopes are rejected rather than silently enabled.

An ADZ import is bounded to 1,000 entries, 50 MiB per entry, 500 MiB total unpacked
data and a 100:1 per-entry compression ratio. Paths, duplicates and passive asset
policy are checked separately. Catalog downloads also have a configurable byte
budget. Session archives use their own budgets and lifecycle.

## Canonical envelope

```json
{
  "format": "TaleWeaver",
  "version": "1.3",
  "adventure": {
    "origin_id": "69d62242-c2cc-4716-8473-a24502955d35",
    "title": "The Harbor Archive",
    "version": "1.0.0",
    "rule_enforcement_mode": "chat",
    "language": "en"
  },
  "protagonist": {"name": "Alex", "role": "Visitor", "description": "A traveler"},
  "scenes": [{"id": "HARBOR", "label": "Harbor", "description": "A quiet quay"}],
  "exits": [],
  "npcs": [],
  "objects": [],
  "quests": [],
  "awards": [],
  "sequences": [],
  "scripts": [],
  "init_script": null
}
```

Exports can also contain authored `visual_presets`, `visual_preset_source`,
`npc_card_settings`, `clothing_settings`, `narrator_settings`, `world_brief`,
`world_brief_sources` and valid top-level `extensions`. They are not all features
of the original project. The compatibility exporter reports or blocks changes
needed for an original-project copy.

## Identity and scope

New template and session storage IDs are UUIDs. Entity and scene IDs are stable
adventure-local reference keys; uppercase names such as `ARCHIVIST` or `IRON_KEY`
are a useful authoring convention, not a requirement to rewrite legacy IDs.
The same local key may exist in another template or a session copy. Always resolve
references in their template/session scope.

`adventure.origin_id` identifies the story across export, installation and updates.
Existing origin keys are preserved; an unpublished template without one receives
a repeatable UUID on export. Catalog comparisons canonicalize UUID spellings and
retain exact, case-sensitive non-UUID legacy keys. Titles do not identify a story.
See [storage identifiers](../storage-identifiers.md).

## Adventure metadata

The following table describes commonly used fields, not every exporter property.
Use the writer and current model definitions when implementing a transfer tool.

| Field | Meaning |
| --- | --- |
| `title`, `teaser` | Display title and hook; editor limits are 50 and 300 characters respectively. |
| `version`, `origin_id` | Authored release version and stable story identity. |
| `creator`, `copyright`, `license`, `license_url` | Story attribution and publication license. |
| `language` | Authored content language; a session can select its own subsequent content language. |
| `original_prompt`, `plot`, `rules`, `intro_text`, `walkthrough` | Authored generation/narrative material. The generated input can use aliases such as `context`; exports use their canonical fields. |
| `image_url` | Cover reference; ADZ packing localizes eligible local images. |
| `rule_enforcement_mode` | `rpg`, `story`, `chat` or `vn`. Legacy `strict_rules` can affect non-VN mechanics selection. |
| `time_per_turn`, `pacing_minutes`, `max_time_per_turn`, `clock_enabled` | Story-clock/pacing controls, not wall-clock playtime. See the mode and time guides. |
| `starting_timestamp`, `time_system`, `time_config` | Starting game minute and calendar configuration. `ingame_timestamp` is not the canonical export field. |
| `selected_tone` | Selected tone object or null. |
| `selected_image_styles` | Array of selected style objects. |
| `generate_scene_images`, `generate_npc_images`, `generate_item_images` | Generation preferences; actual provider/workflow configuration is separate. |
| `min_*`, `max_*`, `*_generation_enabled` | Supported world-builder scope and generation switches. These are not new gameplay permissions. |
| `living_world_settings`, `npc_personality_settings` | Validated defaults inherited when creating an appropriate new session; not live events, minds or notebook contents. |
| `can_damage_npcs`, `npcs_can_damage_protagonist`, `game_over_rules` | Mode-dependent mechanical preferences. |
| `completed_condition`, `gameover_condition`, `*_guard_expression` | Narrative ending conditions and supported deterministic guards. |

VN normalizes RPG combat, quests, awards, sequences and mechanical ending gates
out of its template. It still supports structured progression and persistent
world/item state. See [VN mode](../visual-novel-mode.md),
[VN time](../vn-time-passages.md) and
[the mode policy](../../backend/core/game_modes.py).

## Protagonist and NPCs

`protagonist` defines the starting avatar. Its exported fields include `name`,
`role`, `description`, `goal`, `character`, `profile_image`, vitals and maxima,
`exp`, the scalar attributes (`strength`, `dexterity`, `intelligence`, `wisdom`,
`charisma`, `armor_class`), additional `stats`, `status_effects`,
`starting_inventory` and `starting_equipment`. Supported identity/appearance fields
are handled by their existing models and clothing projections.

An NPC record includes a stable `id`, `name`, `description`, authored `character`
and `goal`, initial location, inventory/equipment, appearance, visibility and
supported metadata/hooks. Exports use stored `current_scene_id`; generated
blueprints commonly use `start_scene_id`, which the application mapper resolves.
NPC inventory is possession, not a list of items that have already been dropped.

`metadata_json.personality_profile` contains authored categorical identity.
`metadata_json.agent_runtime` is a portable seed namespace described in
[its own spec](agent_runtime.md). Current psychological experience, private
notebooks and session memory are not NPC blueprint fields.

## Scenes and exits

Scenes contain `id`, `label`, `description`, `image_url`, optional
`decorative_objects` and scene-entry/leave hooks. Generated inputs can use `name`
for the display label. A scene's description is not an interactable item record.

Exits connect `from_scene_id` to `to_scene_id` and can define `label`,
`exit_type`, `is_locked`, `lock_description`, `code_to_unlock`, `item_to_unlock`,
`rule_to_unlock`, `unlock_expression` and supported traversal/unlock hooks.
Stored exits are directional edges. The generator's `is_bidirectional` convenience
flag can create a reverse edge; do not infer a reverse edge from a display label.
Both endpoints must refer to scenes in the same world scope.

## Objects, clothing and conditions

Object records include identity, description, `item_type`, `is_portable`, initial
location/placement, visibility, inventory and type-specific fields. The current
item-creation editor uses `DEFAULT` for an ordinary item and also offers
`WEAPON`, `WEARABLE`, `CONSUMABLE`, `READABLE`, `CONTAINER`, `SWITCH` and
`CONSTRUCTABLE`. Generated or imported worlds can retain additional established
type strings such as `STATIC`, `PICKABLE`, `TOOL` and `KEY`. `ITEM` also appears
as a display fallback; it is not the ordinary-item type selected by the current
editor.

| Concern | Canonical authored representation |
| --- | --- |
| Equipment | `wearable_slots`, supported scalar `stat_modifier_*` fields, damage/cost fields. |
| Containers | `inventory`, lock state and `code_to_unlock`, `item_to_unlock`, `rule_to_unlock`, `unlock_expression`. Import supports the established metadata mapping. |
| Readable items | `text_log_content`, `text_log_format`, read hooks. |
| Switches | Declared states, initial state, transitions, gates/outcomes and supported success/failure hooks. See the editor and switch schemas. |
| Construction | `combination_ingredients`, combination logic, craft guards and hooks. |
| Clothing | Canonical item identity plus authored clothing metadata and the actor's `visual_profile`; coverage/wear does not replace possession ownership. |

Do not substitute invented fields such as `unlock_code`, `switch_actions` or a
single `stat_modifiers` object for the current export mapping. A compatibility
adapter must explicitly map any external aliases.

Live mutable item properties and physical conditions are session state with
source provenance; they do not require replacing the item's identity. See
[item state](../item-state.md), [physical state](../persistent-physical-state.md)
and [clothing/state reconciliation](../narrated-item-reconciliation.md).

## Quests, sequences and awards

Quests use `id`, `title`, `description`, `goal`, `impact`, `exp_reward`, `status`
(`open`, `completed`, `failed`) and optional `required_*`/`guard_expression` gates.
An `is_main` boolean is not the canonical quest schema. Sequences provide ordered
chapters with their own entry/end conditions, hooks and rewards.

Awards use `key`, `title`, `description`, `tier` (`bronze`, `silver`, `gold`,
`negative`), `requirement` and optional deterministic gates. An exported
`is_earned` value is accepted as blueprint data; it does not grant the receiving
user an achievement. Earned status is resolved from that user's progression.

## Scripts and extensions

Standalone `scripts` records declare `id`, `trigger`, `code`, optional name,
description and target. `init_script` is a top-level canonical field. Its supported
non-VN session initialization and helper-definition behavior are described in the
[scripting reference](../scripting_engine.md). Importing a file stores authored
scripts; it is not a request to execute arbitrary server Python.

The `extensions` envelope accepts up to 32 valid namespace objects, with a
256 KiB UTF-8 serialized-value budget. Unknown/null nested values can survive
transport without becoming executable or activated configuration. See
[`agent_runtime`](agent_runtime.md) for the exact normalization and preflight rules.
Do not embed mutable session state, credentials or provider endpoints in a
portable adventure contract.

## Validation and transfer lifecycle

Structural checks, authoring validation and AI-assisted review are available;
passing an envelope/import check does not prove graph connectivity, script
semantics or identical model behavior. Run the
[authoring validator](../adventure-authoring-validation.md) before sharing.

Normal imports use existing transactions and source/asset checks. A failed import
must not replace the previously valid template. Catalog updates create another
template release so existing playthroughs retain their snapshots and assets.
Full saved-session history, World Info and notebooks belong in a session transfer,
not in this blueprint. Export and publication preparation are separate actions;
preparing a compatible local copy does not publish it online.
