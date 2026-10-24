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
