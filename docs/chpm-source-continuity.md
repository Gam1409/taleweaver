# Historical source recovery and NPC reports

These additions use the existing perception and shared narration review. They
add output fields and bounded source context, without another generative call.
All routing, mode switches, state ownership and request limits remain in place.

## Recovery after simplified RP

A simplified assistant reply records eligible NPC IDs, known speakers, its hash,
revision, scene and game minute in optional `chat_messages.npc_recovery` metadata.
This cursor metadata survives the short diagnostic window. Older saves can
recover only sources whose retained diagnostics still prove their eligibility;
the engine cannot reconstruct unrecorded past psychology.

The next live perception call may classify four historical fragments alongside
the current input. Only eligible observers receive classified public fragments.
Private or unobserved content is excluded. Uncertain fragments remain explicitly
recorded for review by their exact spans; they do not become NPC knowledge.
Malformed historical output does not invalidate independently valid current
perception. If optional history exceeds the input budget, it stays pending.

Recovered observations retain their source scene, minute and exact occurrence.
They enter the current ledger as reported historical evidence. The simulation
clock never moves backwards, and a remembered past event is not declared ongoing.
No past emotion, decision or physical outcome is retroactively invented.

Only a successful shared review commits the cursors of actors whose decisions
also succeeded. Sources are checked again after inference. Changed or unavailable
sources retain their original text and an unavailable diagnostic; they cannot
starve later sources indefinitely. A current verified turn resets the consecutive
failure indicator; it does not mean every historical source has been recovered.

Turn rollback and checkpoints restore source cursors together with psychological
state. Copy/import preserve the metadata with the conversation, using the existing
message-copy lifecycle. This requires the additive Alembic chat-column migration.

## Reported information between NPCs

The reviewer may associate heard speech with an `origin_id` known by the actual
speaker. The bounded catalogue reuses that NPC's agent citations and semantic
hits, followed by recent sources, with fair allocation between actors. It never
provides another NPC's private sources as their own knowledge. Optional report
context yields to the existing review input budget.

A received report retains its own exact utterance and the preceding source
anchors, up to 16 transmissions. Relays share the original evidence roots;
repetition does not manufacture independent confirmation. Receiver prompts show
the received claim, without exposing an ancestor's private source text.

The final transaction rechecks cited origins. Source edits/deletions invalidate
dependent reports and their semantic documents. Copy remaps every dependency
and root; a missing source removes its dependent suffix through the existing
replay path. Reports remain reported information, never automatic world truth,
belief, emotion or action. This is dialogue transmission, not an autonomous
off-scene simulation. Matching the meaning of an utterance to its origin still
depends on model quality and needs live evaluation.
