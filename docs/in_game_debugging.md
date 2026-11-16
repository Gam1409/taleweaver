# In-Game Debugging Guide

TaleWeaver provides owned-session commands to inspect and correct game state
from the chat interface. Debug commands and their technical replies are excluded
from ordinary narration and memory context; see [Debug history scope](debug-history-scope.md).

## Activation

Send `/debug on` in your session to enable its persisted Debug flag. Use
`/debug off` to disable that session flag. These commands are available through
the authenticated, owner-scoped turn path; the environment flag is not required
to opt into session Debug.

To enable the global debug default at backend startup, set this in `.env` and restart:

```env
TALEWEAVER_DEBUG_ENABLED=True
```

The default is false. Most commands require either this global flag or the
session's Debug flag. Some correction handlers explicitly require session Debug,
so use `/debug on` before correcting state. `/debug off` does not override a true
global environment flag. Gameplay Debug is separate from administrator System
Debug and detailed request logging.

## Rolling turn rollback

While gameplay Debug is enabled, TaleWeaver keeps five recent **before-turn**
checkpoints. Open **Debug → Diagnostics → Turn rollback**, choose a point in
Chronicles and confirm restoration. The point's turn number and input preview
identify the turn that will be undone. Later messages and checkpoints are removed;
the play agent is paused after restoration. A running turn must finish first.

These points share the existing checkpoint owner and restore saved session state,
game time, avatar, NPC state, inventories, clothing, physical conditions, scene
continuity and psychological memory. Canonical NPC definitions are now captured
alongside items and maps, so those fields do not remain at their future values.
Ordinary milestones retain their separate five-point limit; manual and pinned
points remain retained. Existing images are referenced rather than copied.
Private NPC notebooks retain their latest contents after rollback; they are not
part of the rewindable psychological history. See [NPC notebooks](npc-notebook.md).

Recording begins with new turns after gameplay Debug is enabled. Older turns
without a snapshot cannot be reconstructed. Old checkpoints missing canonical
item/NPC data report a warning and restore only the fields they actually contain.
This gameplay option is separate from the administrator's detailed diagnostic log.

## Command Syntax

All debug commands are prefixed with `/debug`.
The following are common commands; the registered dispatcher is
[`backend/engine/debug_engine.py`](../backend/engine/debug_engine.py).

| Command | Description |
|---------|-------------|
| `/debug on` / `/debug off` | Enable or disable the session Debug flag. |
| `/debug engine` | Shows server diagnostics (Version, OS, Session ID, etc.). |
| `/debug session` | Shows the current session, scene, time and Debug flag. |
| `/debug scenes` | Lists all scenes in the current adventure with their IDs. |
| `/debug npcs` | Lists all NPCs with IDs and their current location. |
| `/debug items` | Lists all items (inventory and world) with IDs. |
| `/debug exits` | Lists all exits, their destinations, and lock status. |
| `/debug walkthrough` | Unlocks the walkthrough modal for free and shows it in chat. |
| `/debug game_won` | Forces the session into a "Won" state. |
| `/debug game_over` | Forces the session into a "Lost" state. |
| `/debug quest_finished` | Completes the currently active quest. |
| `/debug claim_awards` | Grants all possible awards in the adventure. |
| `/debug exp [amount]` | Grants the specified amount of XP to the avatar. |
| `/debug move_npc "NPC_ID" "SCENE_ID"` | Move an existing session NPC to an existing session scene. |
| `/debug move_player "SCENE_ID"` | Correct the player's location without simulating travel or changing story time. |
| `/debug delete_item [ITEM_KEY\|ID]` | Removes an item from the world or inventory. |
| `/debug open_exit [EXIT_ID]` | Unlocks a specific exit. |
| `/debug szene` | Shows technical details of the current scene. |
| `/debug map` | Shows summary counts of world elements. |
| `/debug log on/off` | Changes the same session Debug flag and its technical chat details; it does not enable raw model telemetry. |

Use the Debug inspector's NPC, clothing and State panels for structured corrections.
They submit registered commands such as `npc_clothing`, `npc_unwear` and
`condition` with validated JSON. The [wardrobe recovery guide](wardrobe-debug-recovery.md)
documents evidence-backed preview, selection and application; those operations
are separate from silently changing a narrative description.

## Practical Examples

### 1. Unlocking the Walkthrough
If you want to check the adventure's solution without spending XP:
`user: /debug walkthrough`

### 2. Resolving Entity Conflicts
To move a session NPC to another existing scene:
`user: /debug move_npc "GUIDE" "HALL"`

Use the IDs returned by `/debug npcs` and `/debug scenes`; they must belong to
this session. Manual movement changes location without deciding a new storyline.

### 3. Finding an Exit ID
If you need to force open a door but don't know the ID:
`user: /debug exits`
(Then use the ID found)
`user: /debug open_exit exit_42`

### 4. Testing Reward UI
To see how the game looks when won:
`user: /debug game_won`
