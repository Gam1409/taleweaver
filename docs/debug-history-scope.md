# Debug transcript and story context

Debug commands and their responses remain saved for inspection. The story feed shows them only when the session's Debug setting is enabled. Hiding them does not delete messages, reverse a correction or change the current world state. A server-wide Debug capability does not force a session's hidden history to appear.

`ChatMessage.is_debug` persists the existing transport flag. New commands, their responses, diagnostics and scoped Debug generation retain it across reloads, copies, exports and replay snapshots. The additive migration defaults existing rows to false. A shared classifier also recognizes legacy command prefixes, diagnostic prefixes and the command's following system reply. The legacy association ends at that reply or a new story narration, so later game events are not hidden; source text is preserved.

Debug user messages do not consume the recent story-turn allowance. Both narration and planning history exclude Debug exchanges. Chronicle input, new memory documents, recall source validation, clothing history and NPC source selection exclude them too. Canonical facts changed by a Debug command remain available through their ordinary world-state owners.

Technical assistant output cannot be claimed by the NPC journal worker. Its old task records do not hold a story-learning lease, schedule retries, count as failed learning or appear in the Characters progress indicator. They remain stored for inspection.

Existing transcripts and summaries are not rewritten. A recalled summary whose required Debug source is unavailable fails the existing source validation. Historical free-form chronicle text is retained; this change does not claim to reconstruct the exact inputs of an earlier model request.

Visibility is separate from rewrite permission. Display toggles do not replace the latest story response. State-changing Debug commands remain replay barriers, and a technical generated response cannot be regenerated as an ordinary narrator answer.
