# VN story initiative

The VN narrator can develop the story and direct NPCs without waiting for a player
command. It can connect actions and consequences, resolve interactions and introduce
compatible developments. There is no one-beat ceiling. The existing Utility request
may propose a principal NPC initiative alongside continuity updates; a missing plan
does not suspend the narrator's initiative. There is no additional LLM call, background
director loop, new model dependency or database migration. Existing VN sessions use
this path. RPG and ordinary Chat retain their own progression contracts.

VN text prioritizes dialogue, character action and story development. Stable room,
appearance and object details remain available for continuity and illustration;
they are not a per-reply description checklist. Prose introduces a scene or describes
meaningful changes, interactions and newly relevant details. Emotional nuance and
consequences still belong in narration; neither scenic paragraphs nor narration
between every line of dialogue are mandatory.

The director receives a bounded premise and guidance, characterization and goals
for the available present NPCs, and two recent attempted initiatives. The full story
frame remains available to the narrator. VN planning receives up to 8,000 characters
of the previous narrator reply, instead of the generic 400-character reference tail.
Longer replies retain the beginning and ending with an explicit omission marker.
This increases tokens in the existing request; production latency has not been measured.

## Player agency and scene rhythm

NPCs can start conversations, act within the scene and depart through known open
exits without a player invitation. The player is never automatically moved or made
to agree. Their next contribution can redirect, interrupt, follow or ignore an NPC.

The former scene-rhythm permission field is no longer requested; legacy responses
containing it are accepted with that extra field ignored. Engaged or settling scenes
and missing closure excerpts no longer veto departures or topic changes. The model
chooses timing from characterization and
dramatic causality. Instructions still encourage emotional continuity rather than
obligatory twists. Pace controls presentation, not an action count. Social reaction
suggestions are a starting point rather than a whitelist of NPC behavior.

Departure requires a present, visible, undefeated, movable NPC, an allowed destination
and an open exit from the current location. Existing movement guards run afterwards.
Player movement and already-resolved NPC movement take precedence. After departure,
the NPC cannot keep speaking here or assume the player follows. Item ownership,
clothing, clock and presence updates still require existing continuity validation.
Mature-content prompt text and insertion hooks are unchanged.

## Continuity, repetition and retries

The narrator receives a continuation reminder: respond after the latest moment,
develop events, avoid recapping unchanged scenery and gestures, and prefer a short
response over padding. Recent attempted directions remain context rather than an
exact-text blacklist. The model can deliberately revisit an action when circumstances
change; the engine does not silently replace it with a passive turn.

Up to four attempted directions are stored under `__vn_story_direction__` in session
JSON, associated with completed narrator messages. They are planning history, not
verified events, NPC journal facts or RAG memories. Incomplete responses do not record
a direction. Normal game mutations use the existing turn transaction; full Regenerate
rewinds directions and NPC movement with the rest of the turn. Rewrite does not run
the director or execute another movement. Malformed optional planning is discarded
with an English warning while valid continuity fields remain usable.

## Compact scene orientation

The same Utility request can refresh `scene_focus`: a current goal, an open question,
and an interpretation of the last observed change with a quote from the previous
completed narrator reply. Observations without matching evidence are cleared;
new player attempts and proposed actions are not observation sources. An exact
quote establishes provenance, not semantic correctness, so all orientation remains
provisional and subordinate to actual dialogue and canonical state.

This replaces a single small object under `__vn_story_direction__`, rather than
appending another history. It is private planning context, never directly added to
NPC journals, notes or RAG facts. It can guide narration even without a `story_beat`.
Completed turns persist it in the existing transaction. Incomplete responses do
not replace it, scene changes discard it, and full regeneration rewinds it. A
missing new focus clears stale orientation instead of carrying a goal indefinitely.

## Voice directions

The shared voice prompt now treats tags as optional, sparse delivery cues. The
per-turn instruction encouraging more tags has been removed. Copies of assistant
history sent to models omit recognized inline angle-bracket delivery cues, including
those separated by speech. Saved dialogue, player/system messages, emotional square
tags and prose describing physical conditions remain intact. New response streaming
still preserves ordinary cues while bounding runaway consecutive tag chains. This
reduces feedback from old sounds; it does not guarantee that a model never repeats.

## Scope and validation

This is narrative initiative within the world, not an off-screen simulation, a new
chapter system or a random-event scheduler. NPC movement flags remain authoritative.
Creative development is not bounded to one step, but it cannot prewrite the player's
decisions or bypass state validation.

Regression tests cover allowed and rejected movement, player separation, scene
transitions without a permission gate, bounded planning history and scene orientation,
malformed responses, the real VN turn pipeline and full regeneration rollback. Voice
tests distinguish output filtering from model-input cleanup. These tests use
deterministic model doubles; narrative quality must also be evaluated in actual play.

## Prompt composition

Keep stable instructions in the system message and variable data in the current
turn block. The VN contract owns narrative authority, player agency, presentation
and formatting. The shared voice block owns optional delivery cues. World state
and resolved mechanical outcomes establish canonical facts; memories, scene focus
and social suggestions are labeled context, not new instructions or guaranteed
outcomes. The final continuation reminder states the immediate task without
repeating the full contracts. Per-turn blocks are separated by blank lines, and
the player's contribution follows the context. Content-setting addenda retain
their existing insertion path.

This follows general guidance on roles, clear boundaries, stable prefixes and
placing the immediate query after long context. It does not assume XML has special
authority or that one ordering is optimal for every local model. Evaluate prompt
changes with the actual model and its chat template, using quiet scenes, active
scenes, interruptions and long conversations. Check new developments, repeated
prose and sounds, player agency, and canonical continuity together.

References consulted:

- [OpenAI: Prompt engineering](https://developers.openai.com/api/docs/guides/prompt-engineering)
- [Anthropic: Prompting best practices and long context](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/long-context-tips)
- [Google: Prompt design strategies](https://ai.google.dev/gemini-api/docs/prompting-strategies)
