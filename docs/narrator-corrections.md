# Narrator corrections

The pencil beside Ideas opens five editorial presets or a custom note (up to
2,000 characters). Choosing a correction does not generate anything. An amber
dot indicates that one correction is queued. Reopen the dialog to inspect,
replace, or remove it.

The next player-triggered narration, Rewrite, or full-turn Regenerate receives
the correction at the end of its system instruction. This placement preserves
the stable prompt prefix and separates the current editorial task from story
data. No prompt position guarantees adherence across models. The instruction
preserves language, technical formatting, character agency, and confirmed
outcomes; feedback is not permission to mutate game state.

The note is never appended to the player's message, chat history, NPC journal,
or RAG documents. It adds no separate LLM call. Pending feedback is scoped to
the session in this browser tab and survives reloads via sessionStorage (with an
in-memory fallback if storage is unavailable). It is not synchronized to other
tabs or devices. Full-turn regeneration retains its existing rollback behavior.

A complete saved narration acknowledges delivery and clears the captured note.
Failures, incomplete streams, commands without narration, and older servers
without acknowledgement leave it queued. A lost acknowledgement can therefore
leave a note queued even if the model received it; inspect or remove it before
the next action if needed. Acknowledgement means the instruction was delivered,
not that a second model verified compliance. An older response cannot clear a
newer replacement note. Automatic play-agent turns and terminal epilogues do not
consume this player-controlled queue.
