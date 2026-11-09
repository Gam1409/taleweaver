# Regenerating the latest turn

The latest saved answer has two separate actions in both the VN story feed and the classic game interface:

- **Rewrite response** replaces narration while retaining the resolved game outcome.
- **Regenerate turn** restores the state before the last player message and runs that same message through the normal game pipeline again. Its outcome and narration may change. A confirmation explains this before starting.

Full regeneration uses the normal LLM timeout settings and streaming route. It does not add a separate short generation deadline.

A pre-turn snapshot must exist. Old replies, imported sessions and copied sessions become eligible after a new supported turn. Normal player messages and `/say` are supported; direct mechanical commands and adventure-generator sessions are excluded. Legacy sessions sharing one avatar with another session cannot be independently rewound.

The display toggles `/debug on`, `/debug off`, `/debug log on` and `/debug log off` preserve the last story reply and its pre-turn snapshot. Rewriting, version restoration and full-turn regeneration ignore these toggles when selecting the latest story message; full regeneration keeps the current debug visibility setting. Other commands that can change game state still replace the replay boundary. If an older application version already replaced a snapshot with a debug command, play a new story turn to capture a usable boundary again.

## Recovery and memory

One durable snapshot is retained per session. It includes the session-owned world, avatar, inventory, NPC state and journal, map discovery, checkpoints, canonical memory summaries and this session's user awards/history. Real playtime is not rewound. Generated assets remain on disk; their saved references are restored with state.

Before rewinding, the completed result is saved as a recovery backup. Errors, incomplete narration and disconnected streams restore that result. Startup also recovers unfinished retries after a process interruption. A repeated regeneration still uses the original pre-turn snapshot, preventing repeated costs, damage or time advancement.

Memory-index epochs advance when restoring state so old embedding jobs cannot publish into the new epoch. Restored journal jobs are returned to the queue. Snapshots are internal recovery records, not part of exported adventures.

The application uses its existing single-worker session lease and foreground scheduler. Running multiple backend workers requires shared concurrency control before enabling this operation across workers.

## Undo in debug mode

**Undo turn** removes the latest supported player action, its response and all
consequences through the same pre-turn snapshot. It restores clothing, items,
character state, location and game time together. Debug visibility remains on;
the Play-Agent remains stopped after the manual rewind. The client reloads the
authoritative state before accepting another action, without automatically
generating a replacement opening when history becomes empty.

Older turns require restoring an existing **Chronicles** checkpoint from before
the desired turn; that restores the checkpoint and discards its later branch.
If no safe snapshot exists, deletion is refused and the current branch is kept.
Undo consumes the latest-turn snapshot. Play a new supported turn to capture a
new one; there is no additional archive of turn snapshots.
