# Dynamic local exploration (experimental)

Enable **Allow new local places** in the in-game settings accordion **Dynamic
exploration**. It is off by default, including existing sessions, so authored
puzzles and fixed maps retain their original behavior. The setting is session-local;
turning it off stops expansion without deleting previously created places.

The Small/Utility mechanics model may propose one unlisted local place only when
the player actually enters it in the current turn. A second bounded structured call
confirms arrival, actor, local reachability, access and scale, and writes a short
label/description in the content language. It uses the same role-specific model and
URL. Past-tense action narration can count; memories, future plans, searching,
questions, invitations alone, NPC-only travel and remote lore do not.

Existing mapped destinations use the normal movement pipeline. A new scene always
belongs to the current location and receives a server-generated UUID-based ID and
a bidirectional return exit. The forest's tavern and the city's tavern are distinct.
Known local names/IDs are checked before creation. Names are Unicode-normalized;
alias interpretation still depends on the model. The model cannot supply scripts,
new usable inventory, NPCs or arbitrary connection endpoints through this feature.

Scale choices:

- **Auto** infers regional versus building scale from the original map/premise on
  the first successful creation and keeps that inference for the session.
- **World / region** permits sites/buildings; incidental small rooms remain scenery.
  A room can become a scene for an evidenced overnight stay, investigation or
  independently persistent use. Whole sites cannot be nested inside new sites.
- **House / investigation** allows individual rooms to become scenes.

Explicit scale overrides are useful for smaller models. A hard cap of 48 generated
places per session, 8 children per parent and depth 3 bounds runaway expansion.
These limits do not create artificial narrative obstacles. At a limit or uncertain
model response, no new map node is made. There is no separate place registry for
mere mentions: those remain in the existing conversation/memory system.

Scene/exit records and the registry are saved before narration consumes the changed
state. The normal game movement, time, script and checkpoint pipeline still runs.
Unentered provisional places are removed. Copy and session export/import retain
the registry and topology; rewind removes locations created after the checkpoint,
including their exits/map nodes. No database migration is needed: the registry uses
a reserved session-state JSON key already carried by saves and checkpoints.

Background images use the session's story preset, scene image profile, style and
tone. They run after the turn commits and do not block entering/playing. The game
shows image status and a retry action; missing nodes/providers or generation failure
leave the scene usable. After a process restart, unfinished image work can be retried
explicitly rather than automatically submitting a duplicate remote job. Late image
results do not recreate rewound/deleted scenes. The queue is for one backend process.

Limits: semantic arrival, invented access, scale and alias interpretation remain
LLM judgments, even with two structured decisions. The engine enforces parent IDs,
existing-exit access checks, bounds and evidence-substring checks; it cannot prove
that a free-form description is spatially truthful. This is not arbitrary continent
expansion, autonomous world simulation, or a guarantee of Qwen 14B accuracy. Tests
mock model responses; actual model behavior requires live gameplay evaluation.

## Existing places and RP clarification

The existing confirmation call now compares a proposed place with a bounded
catalog of canonical scenes, including descriptions, nearby routes and recent
story context. Short, inflected or translated names do not need to match a map
label exactly. For example, entering "the laboratory" while delivering clinical
samples can refer to the existing "Clinical laboratory".

The utility model supplies contextual identity scores. One unambiguous match at
**0.70 or above** selects the existing scene ID; normal route and access guards
still decide whether movement is allowed. Multiple qualifying candidates require
clarification. Unknown IDs and incomplete catalog reviews cannot authorize a new
place. An uncertain existing destination never becomes an unlocked duplicate.

When clarification is needed, the narrator keeps the player in the current
location and asks one short question within the RP. It may name only alternatives
already known to the player or visible through an open local route. It does not
expose IDs, matching scores or validation instructions. This is a destination
question, not a request for permission to continue the conversation.

The catalog is limited to 80 places and 6,000 description characters, with current
and adjacent scenes first. No extra LLM call was added: identity resolution shares
the existing dynamic-place confirmation. A score is the model's contextual rating,
not a calibrated probability or a vector-distance percentage. Runtime tests verify
the threshold, canonical identity and access rules; live interpretation still
depends on the model.

## NPC movement in existing sessions

`/debug moveable all true` enables movement for every NPC currently in the session
and refreshes their allowed scene lists from matching NPCs in the adventure template.
Session-only NPCs retain their existing scene restrictions. This is an explicit,
one-time synchronization; later template edits require running the command again.
`/debug moveable all false` disables movement without changing those lists.
The existing `/debug moveable NPC_ID true` command only toggles one NPC's movement.

Generated exploration locations are accessible to movable NPCs by default, including
locations already generated in a saved session. Authored scene restrictions still
apply to authored locations. Empty allowed scene lists mean unrestricted movement.
Stationary NPCs remain stationary, and locked exits and other world rules still apply.
