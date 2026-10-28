# Regenerating the latest turn

The latest saved answer has two separate actions in both the VN story feed and the classic game interface:

- **Rewrite response** replaces narration while retaining the resolved game outcome.
- **Regenerate turn** restores the state before the last player message and runs that same message through the normal game pipeline again. Its outcome and narration may change. A confirmation explains this before starting.

Full regeneration uses the normal LLM timeout settings and streaming route. It does not add a separate short generation deadline.

A pre-turn snapshot must exist. Old replies, imported sessions and copied sessions become eligible after a new supported turn. Normal player messages and `/say` are supported; direct mechanical commands and adventure-generator sessions are excluded. Legacy sessions sharing one avatar with another session cannot be independently rewound.

## Recovery and memory

One durable snapshot is retained per session. It includes the session-owned world, avatar, inventory, NPC state and journal, map discovery, checkpoints, canonical memory summaries and this session's user awards/history. Real playtime is not rewound. Generated assets remain on disk; their saved references are restored with state.

Before rewinding, the completed result is saved as a recovery backup. Errors, incomplete narration and disconnected streams restore that result. Startup also recovers unfinished retries after a process interruption. A repeated regeneration still uses the original pre-turn snapshot, preventing repeated costs, damage or time advancement.

Memory-index epochs advance when restoring state so old embedding jobs cannot publish into the new epoch. Restored journal jobs are returned to the queue. Snapshots are internal recovery records, not part of exported adventures.

The application uses its existing single-worker session lease and foreground scheduler. Running multiple backend workers requires shared concurrency control before enabling this operation across workers.
