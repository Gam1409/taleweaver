# TaleWeaver Scripting Engine Guide

The scripting engine evaluates bounded Python-style adventure logic through a
restricted AST interpreter. Scripts can define puzzle rules, hooks, world changes
and ending conditions using the exposed `tw` API. This is an adventure-authoring
API, not the NPC agent's memory/tool API; JSON in a private notebook is never run
as a script.

The implementation reference is
[`context.py`](../backend/engine/scripting/context.py), with dispatch in
[`runner.py`](../backend/engine/scripting/runner.py) and interpreter limits in
[`sandbox.py`](../backend/engine/scripting/sandbox.py). The fork does not expose
every API from newer upstream releases: for example, `tw.dialog`, `tw.party` and
arbitrary provider/network calls are not provided by this context.

---

## Table of Contents
1. [Overview & Architecture](#overview--architecture)
2. [Sandbox Security & Limits](#sandbox-security--limits)
3. [Event Triggers & Lifecycle](#event-triggers--lifecycle)
4. [Global Initialization Script & Helper Methods](#global-initialization-script-init_script--helper-methods)
5. [The `tw` Scripting API](#the-tw-scripting-api)
   - [tw.player](#twplayer)
   - [tw.scene](#twscene)
   - [tw.exits](#twexits)
   - [tw.npcs](#twnpcs)
   - [tw.objects](#twobjects-or-twitems)
   - [tw.switches](#twswitches)
   - [tw.vars](#twvars-persistent-state)
   - [tw.story](#twstory)
   - [tw.memories](#twmemories)
   - [tw.game](#twgame)
   - [tw.quests and tw.sequences](#twquests-and-twsequences)
   - [tw.awards](#twawards)
   - [tw.dice](#twdice)
   - [tw.log & tw.debug (Logging & Diagnostics)](#twlog--twdebug-logging--diagnostics)
6. [Practical Examples](#practical-examples)
   - [Example 1: Trapped Ancient Chest](#example-1-trapped-ancient-chest)
   - [Example 2: Gatekeeper Guard Blocking Passage](#example-2-gatekeeper-guard-blocking-passage)
   - [Example 3: Three-Lever Puzzle with Persistent State](#example-3-three-lever-puzzle-with-persistent-state)
   - [Example 4: Boss Encounter & Victory Condition](#example-4-boss-encounter--victory-condition)
   - [Example 5: Turn-Based Survival Countdown](#example-5-turn-based-survival-countdown)
   - [Example 6: Cursed Amulet (Inline Object Script)](#example-6-cursed-amulet-inline-object-script)
   - [Example 7: Ambusher NPC (Inline NPC Script)](#example-7-ambusher-npc-inline-npc-script)
   - [Example 8: Switch Mechanism State & Guard Expression](#example-8-switch-mechanism-state--guard-expression)
   - [Example 9: Global Init Script with Helper Functions](#example-9-global-init-script-with-helper-functions)
7. [Authoring in the World-Editor](#authoring-in-the-world-editor)

---

## Overview & Architecture

While TaleWeaver's generative LLM master creates rich, adaptive prose and roleplay, certain game mechanics (such as combination locks, physical traps, locked gates, and badge criteria) require **explicit host-controlled rules** rather than a prose-only outcome.

```
                           +------------------------+
                           |   Session Start / New  |
                           +-----------+------------+
                                       |
                                       v
                           [Global Init Script]
                           [on_init scripts]
                                       |
                                       v
                           +------------------------+
                           |     Player Action      |
                           +-----------+------------+
                                       |
                                       v
         +-----------------------------------------------------------+
         |                 Player Message Processing                 |
         |  - Scene transition  --> [on_enter_scene scripts]         |
         |  - Entity action     --> [on_interact scripts]            |
         |  - Rule checks & combat --> [on_logic_pass_done scripts]  |
         +-----------------------------+-----------------------------+
                                       |
                     scene or sequence changed this message?
                                       |  yes
                                       v
               [on_turn_end] -> time + status ticks -> [on_turn_start]
                                       |
                                       v
                      LLM narration --> [on_narration_done scripts]
                                       |
                                       v
                           +-----------+------------+
                           |  Narrative & UI State  |
                           +------------------------+
```

Scripts run in `SafeAstInterpreter` and accumulate a `ScriptChangeset` for the
host to apply. This is not a separate operating-system process or a guarantee
that an individual script failure rolls back every earlier changeset operation.
Test the complete hook and its host application path, including failures.

VN disables the RPG event-script generation/initialization path. Use the existing
VN progression and state owners for VN sessions; a stored script is not evidence
that it executes in every mode.

---

## Sandbox Security & Limits

To ensure player safety and server reliability:

- **Pure AST Interpretation**: Scripts are evaluated node-by-node against a strict AST whitelist without calling unrestricted `eval()`, `exec()`, or invoking CPython bytecode.
- **Custom Functions & Lambdas**: Scripts can declare custom helper functions (`def func_name(arg1, arg2=default): ...`) and lambda expressions (`lambda x: ...`). Return values are safely handled via internal signal exceptions.
- **No System Calls or Imports**: Statements like `import`, `from ... import`, `open()`, `eval()`, or `exec()` are rejected at parse time.
- **No Private or Dunder Identifiers**: Accessing attributes or defining functions starting with an underscore (e.g. `_internal`, `__class__`, `__subclasses__`, `__globals__`, or `__dict__`) is strictly forbidden.
- **No Introspection Escapes**: `str.format`, `format_map` and `mro` are blocked (format strings could otherwise walk `{0.__globals__}`), as are frame/generator/code attributes (`f_*`, `gi_*`, `cr_*`, `ag_*`, `tb_*`, `co_*`). Use f-strings or `+` for text.
- **Instruction & Time Budget**: Each script execution is capped at **10,000 steps** and **2 seconds** (`ScriptTimeoutError`), preventing infinite loops and CPU exhaustion.
- **Resource Protections**: Script source is capped at **100,000** characters before parsing. Strings, lists, tuples and dicts are capped at **100,000** elements/characters, `range()` at 100,000 elements, and integers at 10,000 bits (`ScriptSecurityError`). Amplifying operations such as `replace`, separator-heavy `join`, percent formatting, container text conversion and list/dict growth are checked before allocation or mutation, including unbound builtin methods. Facade arguments and attribute writes also have a bounded expanded payload; cyclic payloads are rejected. These are interpreter limits, not process isolation or a total process-memory quota.
- **Safe Builtins**: Available built-ins are restricted to `abs`, `all`, `any`, `bool`, `dict`, `float`, `int`, `len`, `list`, `max`, `min`, `print`, `range`, `round`, `str`, `sum`, `tuple`.
- **Inline conditionals**: `a if condition else b` is supported.

---

## Event Triggers & Lifecycle

Scripts declare a trigger event and an optional target entity or scene.

| Trigger | When it Executes | Target Field Usage |
| :--- | :--- | :--- |
| `on_init` | When a new game session starts, immediately after initial world manifest and entity state setup. | Global (omit `target_id`, or use null/empty). |
| `on_turn_start` | When a new in-game turn begins, i.e. right after the player's scene or the active sequence changed (after `on_turn_end` of the previous turn, before narration). | Global (omit `target_id`, or use null/empty). |
| `on_enter_scene` | When the player enters a new scene. | Specific `scene_id` or empty for any scene. |
| `on_interact` | When a supported entity interaction dispatches this hook; a mention alone is not a guaranteed trigger. | Specific `entity_id` (NPC or object) or empty for all. |
| `on_logic_pass_done` | After game mechanics and state mutations finish, before narration is generated. | Global (omit `target_id`, or use null/empty). |
| `on_narration_done` | After narration generation completes, before final turn persistence. | Global (omit `target_id`, or use null/empty). |
| `on_turn_end` | When the current in-game turn ends, i.e. when the player's scene or the active sequence changed (before `on_turn_start` of the next turn). | Global (omit `target_id`, or use null/empty). |

> **In-game turns vs. player messages:** An in-game turn spans all player messages within one scene and sequence. Base time (`time_per_turn`), status-effect ticks, and the `on_turn_end` / `on_turn_start` hooks only fire on a scene or sequence change. Use `on_logic_pass_done` or `on_narration_done` for logic that must run on every player message.

### Inline Entity Triggers

In addition to standalone script assets, TaleWeaver allows configuring short inline scripts directly on entities, NPCs, scenes, exits, protagonist, and sequences via the World Editor. These execute automatically during specific interactions.

| Entity Type | Available Triggers / Guards | Description |
| :--- | :--- | :--- |
| **Objects (General)** | `on_pickup_script`, `on_pickup_text` | Executes when the item is taken into inventory. |
| | `on_drop_script`, `on_drop_text` | Executes when the item is dropped into the scene. |
| **Wearables & Weapons** | `on_equip_script`, `on_equip_text` | Executes when the player equips a WEAPON or WEARABLE. |
| | `on_unequip_script`, `on_unequip_text` | Executes when the player unequips a WEAPON or WEARABLE. |
| **Readable Items** | `on_read_script`, `on_read_text` | Executes when the player inspects or reads this item. |
| **Container Items** | `unlock_expression` *(Guard)* | Deterministic Python boolean expression evaluated when attempting to unlock. If false, unlocking fails. |
| | `on_unlock_success_script`, `..._text` | Executes immediately when this container is successfully unlocked. |
| | `on_unlock_failure_script`, `..._text` | Executes when unlocking this container fails or is blocked by guard. |
| **Constructable Items** | `craft_guard_expression` *(Guard)* | Optional Python boolean expression evaluated in addition to ingredients. If false, crafting fails. |
| | `on_craft_success_script`, `..._text` | Executes when this constructable item is successfully crafted. |
| | `on_craft_failure_script`, `..._text` | Executes when crafting fails or is blocked by guard. |
| **NPCs** | `on_defeat_script`, `on_defeat_text` | Executes when the NPC is defeated. Use to spawn loot or change state. |
| | `on_protagonist_enters_scene_script` | Executes when the player enters the room containing this NPC. |
| **Scenes** | `on_enter_scene_script`, `..._text` | Executes when the player enters this specific scene. |
| | `on_leave_scene_script`, `..._text` | Executes immediately when the player leaves this specific scene. |
| **Exits** | `on_open_exit_script`, `..._text` | Executes when the player opens or traverses this exit. |
| | `on_exit_used_script`, `..._text` | Transition Trigger: Executes specifically when the player successfully traverses this exit to enter the destination scene. |
| | `unlock_expression` *(Guard)* | Deterministic Python boolean expression evaluated when unlocking. If false, unlocking fails. |
| | `on_unlock_success_script`, `..._text` | Executes immediately when this exit is successfully unlocked. |
| | `on_unlock_failure_script`, `..._text` | Executes when unlocking this exit fails or is blocked by guard. |
| **Switches** | `gates.expression` *(Guard)* | Deterministic Python boolean condition required for a specific transition. |
| | `on_success_script` | Executes when any state transition succeeds on this switch (or transition-specific). |
| | `on_failure_script` | Executes when any state transition fails on this switch (or transition-specific). |
| **NPC combat** *(metadata)* | `attack_mode: ATTACK_ON_SIGHT` | The NPC starts turn-based combat as soon as the protagonist enters its scene. |
| | `attack_trigger` *(Hard Rules + Guard)* | `required_item_id`, `required_scene_id`, `required_defeated_npc_id`, `guard_expression`: the NPC attacks once when all are met while the protagonist shares its scene. |
| **Special attacks** (protagonist & NPC `special_actions` entries) | `on_success_script`, `..._text` | Executes after a successful d20 success roll. A `special` dict (`id`, `name`, `caster`, `target`, `success`, `crit`, `fumble`, `roll`, `dc`) is in scope. |
| | `on_failure_script`, `..._text` | Executes when the success roll fails. |
| | `unlock_required_item_id`, `unlock_required_scene_id`, `unlock_required_defeated_npc_id`, `unlock_guard_expression` *(Hard Rules + Guard, protagonist only)* | A locked special unlocks after the turn in which all configured conditions are met; a system message (plus optional `unlock_text`) announces it. |
| **Protagonist** | `on_hp_change_script`, `..._text` | Executes when protagonist HP changes (e.g. taking damage or healing). |
| | `on_status_change_script`, `..._text` | Executes when protagonist status effects or conditions change. |
| **Sequences** | `on_start_sequence_script`, `..._text` | Executes immediately when a sequence chapter becomes active. |
| | `on_end_sequence_script`, `..._text` | Executes immediately when a sequence chapter is completed. |
| **Quests (Sidequests)** | `required_item_id`, `required_scene_id`, `required_defeated_npc_id` *(Hard Rules)* | Deterministic entity conditions required to complete quest. |
| | `guard_expression` *(Guard)* | Deterministic Python boolean expression required for completion. Evaluated in Pass 1.5. |
| **Awards (Achievements)** | `required_item_id`, `required_scene_id`, `required_defeated_npc_id` *(Hard Rules)* | Deterministic entity conditions required to grant award. |
| | `guard_expression` *(Guard)* | Deterministic Python boolean expression required for granting. Evaluated in Pass 1.5. |
| **Adventure (Victory)** | `completed_guard_expression` *(Guard)* | Deterministic Python boolean expression required for game victory. Triggers victory deterministically and blocks hallucinated win intents. |
| **Adventure (Defeat)** | `gameover_guard_expression` *(Guard)* | Deterministic Python boolean expression triggering game over. Evaluated in Pass 1.5; blocks hallucinated game-over intents. |

### Cardinal Rule: Soft Rules vs. Hard Rules (Mutual Exclusivity)

For **all assets** in TaleWeaver (Win/Loss conditions, Sequences, Quests, Awards, Exits, Containers, and Switches):
> [!IMPORTANT]
> **Use EITHER a soft narrative rule OR deterministic hard rules / scripted guards, but NOT both on the same asset.**
> 
> Mixing a narrative soft rule and a scripted guard expression on the same asset causes ambiguous triggers and LLM hallucination conflicts. If an asset has hard rules or guard expressions, leave its soft narrative rule empty or purely decorative. If an asset relies on narrative GM judgment, leave its hard rules and guard expressions empty.

### Deterministic Guard Expressions

Deterministic guards (`unlock_expression` on containers and exits, `craft_guard_expression` on constructables, `gates.expression` on switches, `completed_guard_expression` / `gameover_guard_expression` on the adventure, and `guard_expression` on sequences, sidequests, and awards) evaluate safe Python expressions against the `tw` context:
- `tw.switches.get_state('POWER') == 'ON'`
- `tw.vars.get('has_badge', False) == True and tw.player.hp > 20`
- `tw.player.has_item('KEYCARD_RED') or tw.switches.is_state('OVERRIDE', 'ACTIVE')`
- `tw.vars.get('boss_defeated') == True and tw.player.has_item('MOB_LEDGER')`
- `tw.vars.get('countdown', 1) <= 0 or tw.vars.get('cover_blown', False) == True`

If the expression evaluates to truthy, the guard passes; otherwise, the action or completion is blocked deterministically. `tw.switches.get(...)` returns a proxy, so compare its `.state`, call `get_state(...)`, or use `is_state(...)`; comparing the proxy itself to a string does not read its state. Initialize required variables or supply defaults before evaluating a guard.

### Priority Execution
The current `ScriptRunner` iterates the stored script array in order. The editor
can store a `priority` value, but the runner does not sort by it. Do not rely on
that UI field to establish execution dependencies. Keep dependent operations in
one script or verify the actual stored order.

Targets are exact matches. A literal `target_id: "*"` is not a wildcard in the
current dispatcher. Omit the target for a global hook. `is_active: false` skips a
standalone script.

---

## Global Initialization Script (`init_script`) & Helper Methods

In complex adventures, multiple scripts often need to share common utility logic, mathematical calculations, custom state machines, or common inventory transactions. Furthermore, adventures often require initializing starting variables, reputation meters, or world flags before the player's first turn.

The **Global Initialization Script** solves this by providing a single centralized script stored at the top level of the adventure manifest (`init_script`).

### Lifecycle & Execution Model

The initialization script runs under a dual lifecycle model:

1. **Session Creation (Run Once)**:
   When a player begins a supported non-VN game session, the initialization script is evaluated before player actions occur.
   - The current session-start adapter applies script variables, story flags,
     HP/mana/stamina deltas and initial narrative messages. Script variables are
     stored in `__script_vars__`; flags and vitals use their own state owners.
     Do not rely on every other changeset operation (such as inventory transfers,
     exit updates or NPC movement) being applied during initialization.
   - The engine automatically records `__init_script_executed__ = True` so setup logic does not re-run on subsequent turns.
   - Any standalone scripts marked with the `on_init` trigger also fire during this phase.

2. **Every Turn Scope Injection (Reusable Methods & Constants)**:
   Whenever an event script fires during gameplay (`on_turn_start`, `on_interact`, `on_enter_scene`, `on_turn_end`, etc.), the engine loads function definitions (`def ...`) and top-level constants from the initialization script and injects them directly into the script's global execution scope.
   - You can call your helper functions directly from any event script without repeating code!
   - Top-level expression statements are skipped during helper loading. Keep
     constant assignments pure: only function definitions and assignments whose
     outer value is a literal/container are selected, not arbitrary setup code.
     Place one-time effects in the session initialization body.

### Defining Reusable Helper Functions

You can declare custom functions using standard Python `def` syntax, including parameters, default values, and `return` statements:

```python
# --- Global Variables & Constants ---
DEFAULT_GOLD = 50
MAX_REPUTATION = 100

tw.vars.set("gold", DEFAULT_GOLD)
tw.vars.set("reputation", 10)
tw.vars.set("solved_puzzles", [])


# --- Reusable Helper Functions ---
def add_gold(amount):
    current = tw.vars.get("gold", 0)
    tw.vars.set("gold", current + amount)
    tw.story.show_message("You gained " + str(amount) + " gold! Total: " + str(current + amount))


def spend_gold(amount):
    current = tw.vars.get("gold", 0)
    if current < amount:
        tw.story.show_message("Not enough gold! Needed: " + str(amount) + ", Have: " + str(current))
        return False
    tw.vars.set("gold", current - amount)
    tw.story.show_message("You spent " + str(amount) + " gold. Remaining: " + str(current - amount))
    return True


def can_access_sanctum():
    rep = tw.vars.get("reputation", 0)
    return rep >= 25 and tw.player.has_item("AMULET_OF_PASSAGE")
```

### Calling Helpers in Event Scripts

Inside an `on_interact` script attached to `NPC_MERCHANT`:
```python
# The merchant offers a health potion for 20 gold
if spend_gold(20):
    tw.player.heal(30)
    tw.story.show_message("The merchant smiles and hands you a steaming vial of healing draught.")
```

Inside an `on_enter_scene` script attached to `SCENE_INNER_SANCTUM`:
```python
if not can_access_sanctum():
    tw.story.show_message("A divine barrier repels you! Your reputation is insufficient.")
    tw.player.damage(10)
```

---

## The `tw` Scripting API

The global `tw` object is injected into every script execution environment.

### `tw.player`

The player proxy exposes `.name`, `.hp`, `.mana`, `.stamina` and `.xp` reads, with
explicit changeset operations:

- `modify_hp(delta)`, `damage(amount)`, `heal(amount)`.
- `modify_mana(delta)`, `modify_stamina(delta)`, `modify_xp(delta)`.
- `get_stat(name, default=0)`, `set_stat(name, value)`.
- `has_item(item_id)`, `give_item(item_id, name=None, description=None)`,
  `add_item(...)` (alias), `remove_item(item_id)`.
- `has_status_effect(name)`, `add_status_effect(name)`, `remove_status_effect(name)`.

These methods record supported effects; the host applies its mode and state rules.
The proxy does not expose a general `.inventory` property.

### `tw.scene`

- `.id`: current scene key, reflecting a pending scripted teleport.
- `.npcs`, `.items`: lists of proxies in that scene.
- `teleport(target_scene_id)`: propose a scripted scene transition.
- `get_attribute(name, default=None)`, `set_attribute(name, value)`: session scene
  attributes stored through the script-variable mechanism.

There are no direct `.name`, `.description` or `.entities` properties on this proxy.

### `tw.exits`

Prefer explicit source/destination pairs:

- `is_locked(from_scene_id, to_scene_id) -> bool`.
- `unlock(from_scene_id, to_scene_id)`.
- `lock(from_scene_id, to_scene_id, reason=None)`.

`unlock("FROM:TO")` and `lock("FROM:TO", reason="...")` also support a combined
route key. The compatibility one-argument lookup depends on existing exit-state
keys; an arbitrary `WorldExit.id` does not guarantee a match. There are no
`hide()`/`reveal()` methods on `tw.exits`.

### `tw.npcs`

`get(id)` returns an NPC proxy; `all()` and `exists(id)` inspect the scoped manager.
The manager offers `say(id, text)`, `move(id, scene_id, spatial_position=None)`,
`move_to_player(id, spatial_position=None)`,
`drop_item(npc_id, item_id, scene_id=None, spatial_position=None)`,
`give_item(npc_id, item_id_or_dict)`, `kill(id, drop_inventory=True)` and `attack(id)`.

An NPC proxy has `.id`, `.name`, `.hp`, `.is_defeated`, `.current_scene_id`,
`.inventory` and `.is_hidden`, plus:

- `say(text)`, `move_to(scene_id, spatial_position=None)`, `move_to_player(...)`.
- `has_item(id)`, `give_item(item_id_or_dict)`,
  `drop_item(id, scene_id=None, spatial_position=None)`.
- `modify_hp(delta)`, `kill(drop_inventory=True)`, `die()`, `attack()`.
- `set_hidden(value)`, `get_attribute(name, default=None)`, `set_attribute(name, value)`.

Use `modify_hp(-amount)` rather than nonexistent NPC `.damage()`/`.heal()` methods.
Movement shortcuts `current`, `here` and `player` resolve to the player's scene.
Explicit scripting authority is distinct from what an autonomous NPC can perceive
or request through its observer-scoped tools.

### `tw.objects` (or `tw.items`)

`get(id)` returns an object proxy; `all()` and `exists(id)` inspect the manager.
Use the object proxy for `move_to_scene(scene_id, spatial_position=None)`,
`give_to_npc(npc_id)`, `set_hidden(value)`, `lock()` and `unlock()`.
Shared entity properties include `.id`, `.name`, `.current_scene_id`, `.is_hidden`,
`get_attribute(...)` and `set_attribute(...)`.

Use `tw.player.give_item(...)`/`remove_item(...)` for the supported player inventory
operations. Manager methods named `add_to_player`, `remove_from_player`,
`add_to_scene`, `hide`, `reveal` and `move_to_scene` are not part of this API.

Switch objects also offer `.state`/`.switch_state`, `get_state()`, `is_state(value)`,
`set_state(value)`, `flip(target_state=None)` and `toggle()`. For explicit outcome
control use the dedicated switch API below.

### `tw.switches`

- `get(id_or_name)` (also `tw.switch(id_or_name)`) returns a `SwitchProxy`.
- `get_state(id_or_name) -> str`, `is_state(id_or_name, state) -> bool`.
- `set_state(id_or_name, state, apply_outcomes=True)` records a state change.
- `flip(id_or_name, target_state=None, apply_outcomes=True) -> str` and
  `toggle(id_or_name, apply_outcomes=True) -> str`.
- A proxy has `.state`, `.switch_state`, `.states`, `.initial_state`, `get_state()`,
  `is_state(value)`, `set_state(value, apply_outcomes=True)`,
  `flip(target_state=None, apply_outcomes=True)` and `toggle(apply_outcomes=True)`.

State writes and configured outcomes still depend on the receiving host path.
A scripted switch API is not an LLM inference permission.

### `tw.vars` (Persistent State)

`get(key, default=None)` reads and `set(key, value)` records JSON-compatible script
variables in `__script_vars__`. The current proxy has no `has()` or `delete()` API;
use a documented sentinel/default value where a presence distinction is needed.

`tw.flags.get(key, default=False)` and `tw.flags.set(key, value=True)` operate on
the separate story-flag projection.

### `tw.story`

- `show_message(text)`, `narrate(text)`, `message(text)` emit narrative messages.
  Root aliases include `tw.narrate(text)` and `tw.show_message(text)`.
- `system_message(text)`, `system(text)` emit system messages; `tw.system(text)`
  is a root alias.
- `reject_action(reason)` records a host-visible rejection.
- `debug(...)` emits enabled debug diagnostics.

Use `tw.log(...)` for server logging; `tw.story.log` does not exist.

### `tw.memories`

`add(description, scope="global", emotion="neutral")` records a world-memory
proposal in the script changeset. Scope is `local` or `global`; emotion is
`positive`, `negative` or `neutral`. This is not a direct write into an avatar's
private notebook or a guarantee that every memory enters a bounded recall prompt.

### `tw.game`

- `.time`: current in-game minute supplied to the context.
- `win(reason=None)` and `game_over(reason=None)` request terminal outcomes.
- `set_completed_condition(text)`, `set_gameover_condition(text)`.
- `set_completed_guard_expression(expression)`, `set_gameover_guard_expression(expression)`.

The method names are `win` and `game_over`, not `set_victory` or `set_game_over`.

### `tw.quests` and `tw.sequences`

Quests expose `complete(id)`, `fail(id)` and `is_completed(id)`. There is no
`activate()` method. `tw.sequences.advance()` and `complete_current()` request
completion of the current sequence. Mode restrictions still apply.

### `tw.awards`

`grant(key)` requests an achievement grant through the host progression path.
It is distinct from a blueprint's exported `is_earned` display field.

### `tw.dice`

`roll(dice_string)` accepts expressions such as `"2d6+1"`; `d20()` rolls one d20.
The implementation uses pseudo-random draws and does not expose a reproducible
seed contract, `d6()` or `random()`. Use `roll("1d6")` for one six-sided die.

### `tw.log` & `tw.debug` (Logging & Diagnostics)
Provides simple, clean logging methods to inspect state during development and playtesting:

#### 1. Server Console Logging
Outputs diagnostics directly to the server terminal/process logs without showing anything to the player in-game:
- `tw.log(*args, sep=" ")`: Outputs an informational log entry (`[Script Log] ...`) to the server console.
- `tw.log.info(*args, sep=" ")`: Outputs an informational message to the server console.
- `tw.log.warn(*args, sep=" ")` / `tw.log.warning(*args, sep=" ")`: Outputs a warning message to the server console.
- `tw.log.error(*args, sep=" ")`: Outputs an error message to the server console.
- `tw.console.log(*args, sep=" ")`: JavaScript-style alias for `tw.log()`.
- `print(*args, sep=" ")`: Safe built-in Python `print()` routing directly to the server console logger.

```python
# Inspect variable state in server console
tw.log("Player entered chamber with key:", tw.player.has_item("KEY_GOLD"))
tw.log.warn("Low player HP detected:", tw.player.hp)
print("Standard print also routes safely to the server console!")
```

#### 2. In-Game Debug Notifications
Emits interactive diagnostic messages inside the game's message feed. **Only displayed when Debug Mode is ON** (`debug_mode` enabled in game settings or session):
- `tw.debug(*args, sep=" ")` / `tw.debug_message(*args, sep=" ")`: Emits an in-game system notification (`[DEBUG: Script] ...`) visible in the in-game chat when Debug Mode is active. Also logs to the server console at DEBUG level.
- `tw.story.debug(*args, sep=" ")`: Alias via the story proxy.
- `tw.log.in_game(*args, sep=" ")`: Explicit helper to emit an in-game debug notification.

```python
# Only visible to developers/playtesters when Debug Mode is ON
tw.debug("Door lock status:", tw.exits.is_locked("SCENE_A", "SCENE_B"))
if tw.switches.is_state("LEVER_01", "ON"):
    tw.debug("Switch mechanism active, calculating door bypass...")
```

---

## Practical Examples

### Example 1: Trapped Ancient Chest
Trigger: `on_interact`  
Target: `CHEST_GILDED`

```python
# Check if the chest trap was already triggered
if not tw.vars.get("chest_trap_sprung", False):
    tw.vars.set("chest_trap_sprung", True)
    
    # Inflict trap poison damage
    tw.player.damage(18)
    tw.story.show_message(
        "A hidden needle snaps forward from the lock mechanism! Poison burns through your veins (-18 HP)."
    )
    tw.memories.add("Triggered a poison needle trap on the gilded chest.")
    
    # Reveal a secret compartment key on the floor
    tw.objects.get("KEY_BRASS").set_hidden(False)
```

---

### Example 2: Gatekeeper Guard Blocking Passage
Trigger: `on_enter_scene`  
Target: `SCENE_CASTLE_GATES`

```python
# Check if the player possesses the royal seal
if not tw.player.has_item("ROYAL_SIGNET"):
    # Lock the inner courtyard exit
    tw.exits.lock(
        "SCENE_CASTLE_GATES",
        "SCENE_COURTYARD",
        reason="Only bearers of the Royal Signet may enter.",
    )
    tw.story.show_message("The castle guard steps forward, barring the iron gate.")
else:
    # Unlock and allow passage
    tw.exits.unlock("SCENE_CASTLE_GATES", "SCENE_COURTYARD")
    tw.story.show_message(
        "The guard notices the Royal Signet ring, salutes respectfully, and raises the heavy portcullis."
    )
```

---

### Example 3: Three-Lever Puzzle with Persistent State
Trigger: `on_interact`  
Target: the exact lever ID, for example `LEVER_BLUE` (use a separate script for each lever)

```python
# Track the state of 3 levers: lever_1, lever_2, lever_3
tw.vars.set("lever_blue", True)

b = tw.vars.get("lever_blue", False)
r = tw.vars.get("lever_red", False)
g = tw.vars.get("lever_gold", False)

if b and r and g and not tw.vars.get("vault_unlocked", False):
    tw.vars.set("vault_unlocked", True)
    tw.exits.unlock("CHAMBER", "VAULT")
    tw.story.show_message(
        "With a resonant chime, all three mechanisms lock into place and the massive vault door unseals!"
    )
    tw.awards.grant("PUZZLE_MASTER")
```

---

### Example 4: Boss Encounter & Victory Condition
Trigger: `on_interact`  
Target: `NPC_SHADOW_LORD`

```python
# If the player uses the Sunstone against the Shadow Lord
if tw.player.has_item("RELIC_SUNSTONE"):
    tw.story.show_message(
        "You raise the Sunstone! Blinding solar radiance floods the chamber, dissolving the Shadow Lord into harmless embers."
    )
    tw.quests.complete("MAIN_QUEST_SLAY_SHADOWS")
    tw.awards.grant("SAVIOR_OF_THE_REALM")
    tw.game.win("The realm is saved! The eternal darkness has been banished forever.")
else:
    tw.player.damage(25)
    tw.story.show_message(
        "The Shadow Lord's aura lashes out in icy tendrils (-25 HP). You need a source of holy light!"
    )
```

---

### Example 5: Turn-Based Survival Countdown
Trigger: `on_turn_end`  
Target: omitted (global)

The countdown advances once per in-game turn (scene or sequence change). For a per-message countdown use `on_narration_done` instead.

```python
# Increment turn counter
turn = tw.vars.get("collapse_turn", 0) + 1
tw.vars.set("collapse_turn", turn)

remaining = 6 - turn
if remaining > 0:
    tw.story.show_message(
        "The cavern tremors intensify! " + str(remaining) + " turn(s) before total collapse."
    )
else:
    tw.game.game_over("The cavern roof collapsed, burying all beneath tons of solid rock.")
```

---

### Example 6: Cursed Amulet (Inline Object Script)
Trigger: `on_equip_script` (Configured directly on the `AMULET_OF_DOOM` item)

```python
# Apply a curse when equipped
tw.vars.set("cursed_hp_drain", True)
tw.story.show_message(
    "As the amulet touches your skin, an icy chill grips your heart. You feel your vitality draining away."
)
```

Trigger: `on_unequip_script` (Configured directly on the `AMULET_OF_DOOM` item)

```python
# Remove the curse when unequipped
tw.vars.set("cursed_hp_drain", False)
tw.story.show_message(
    "You tear the amulet from your neck, gasping for breath. The icy grip subsides."
)
```

---

### Example 7: Ambusher NPC (Inline NPC Script)
Trigger: `on_protagonist_enters_scene_script` (Configured directly on the `GOBLIN_AMBUSHER` NPC)

```python
# The NPC immediately attacks the player upon entering the scene
tw.player.damage(5)
tw.story.show_message(
    "The goblin leaps from the shadows, scoring a quick hit with a rusty dagger! (-5 HP)"
)
tw.memories.add("A goblin ambushed me from the shadows.")
```

---

### Example 8: Switch Mechanism State & Guard Expression
Trigger: `on_interact` (or switch transition trigger)  
Target: `LEVER_POWER_GRID`

```python
# Check state of another mechanism before powering the main grid
if tw.switches.is_state("VALVE_COOLANT", "OPEN"):
    tw.switches.set_state("LEVER_POWER_GRID", "ONLINE")
    tw.exits.unlock("CHAMBER", "VAULT")
    tw.story.show_message(
        "Coolant surges into the coils. The main power grid hums online and the vault unseals!"
    )
else:
    tw.story.show_message(
        "The lever clicks, but nothing happens. A red warning light blinks: 'Coolant valve must be opened first!'"
    )
```

**Using Guard Expressions (`gates.expression`):**  
Within the Switch Configurator, a transition to `"ONLINE"` can declare a deterministic guard condition:
```python
tw.switches.get_state("VALVE_COOLANT") == "OPEN" and tw.player.has_item("SAFETY_KEY")
```
If this condition evaluates to `False`, the transition is blocked and the transition's `fail_message` is narrated to the player.

---

### Example 9: Global Init Script with Helper Functions
Configured in: **Global Initialization Script** (`init_script`)

```python
# Initialize starting adventure variables
tw.vars.set("investigation_stage", 1)
tw.vars.set("clues_found", 0)
tw.vars.set("bribe_accepted", False)


# Reusable method available across all scene and turn scripts
def discover_clue(clue_name):
    count = tw.vars.get("clues_found", 0) + 1
    tw.vars.set("clues_found", count)
    tw.story.show_message("Discovered clue: " + str(clue_name) + " (" + str(count) + "/3)")
    if count >= 3:
        tw.quests.complete("QUEST_FIND_EVIDENCE")
        tw.story.show_message("All clues uncovered! The conspiracy is exposed.")


def advance_investigation():
    stage = tw.vars.get("investigation_stage", 1) + 1
    tw.vars.set("investigation_stage", stage)
    return stage
```

Event Script using `discover_clue` (Trigger: `on_interact`, Target: `ITEM_SECRET_JOURNAL`):
```python
discover_clue("Conspirator Journal")
tw.player.remove_item("ITEM_SECRET_JOURNAL")
```

---

## Authoring in the World-Editor

You can manage all scripts visually inside TaleWeaver:

1. Navigate to the **Adventure Editor** for your adventure.
2. Select the **Scripts** tab from the navigation sidebar.

### Event Scripts & Triggers
All scripts are managed directly in the **Scripts** tab:
- **Session Initialization**: To execute logic when a new game session starts (initializing variables, quest flags, starting state), create an event script with the **`on_init`** ("On Session Init") trigger.

- Click **New Script** to open the script authoring modal:
  - Enter a human-readable **Name** and unique **Script ID**.
  - Select the desired **Trigger** (`on_init`, `on_turn_start`, `on_enter_scene`, `on_interact`, `on_logic_pass_done`, `on_narration_done`, `on_turn_end`).
  - Optionally pick a **Target** scene or entity using the autocomplete selector.
  - The editor exposes **Priority**, but current runtime dispatch follows stored array order; see the execution-order note above.
  - Use the **Insert Snippet** dropdown to paste starter code.
- Click **Check Syntax** to verify Python syntax, AST safety, and trigger parameters before saving.
- Click **Create Script** or **Save Changes** to commit the script into the adventure manifest.
