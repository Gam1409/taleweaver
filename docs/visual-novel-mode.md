# Visual Novel mode

Choose **Visual Novel** when creating a story. The mode uses the existing story tone,
content language and visual style. It changes both the narration contract and the
game capabilities: no quests, XP, achievements or combat mechanics. Places,
possessions, discovery, conversation history and saved sessions remain available.

Start with a new VN story for a coherent cast and premise. Sessions linked to a
live template use its current mode; portable sessions without that template use
their saved manifest. Editing a template is not an automatic conversion of an
existing cast and history. The first version provides no in-session VN/JRPG switch.

## Narration

In **Session settings → Story & world**, expand **Visual novel narration** and choose **Leisurely**,
**Balanced** (default) or **Brisk**, then save. Pace controls how much of an
interaction a reply develops. It does not authorize a time jump, a relationship
commitment or a decision on behalf of the player.

The narrator writes short dialogue and prose blocks from the protagonist's limited
perspective, responds to the player's contribution and stops at the next meaningful
decision. It preserves the session's content language. Character names and technical
voice tags retain their existing identities. Narration is a separate VN contract,
not the RPG or Chat format with another paragraph appended.

## Story time

The continuity model estimates elapsed minutes for completed actions, including
waiting, travel and sustained conversation in one room. A brief exchange can take
zero whole minutes; there is no automatic five-minute tick for every message.
Mentioning tomorrow, recalling yesterday or asking the time does not itself move
the clock. The narrator receives the updated clock before writing the reply.

For VN, the existing `extra_time_minutes` API field means **total elapsed minutes**,
not a surcharge on a base turn. A scene change adds the configured default duration
only when the same action has no explicit duration. Configured maximum duration
still applies, with an additional 1,440-minute bound per action. RPG and Chat time
semantics are unchanged. Time interpretation remains model-dependent; the code
does not infer elapsed time from language-specific keywords or real request latency.

An explicit completed time passage has a separate, source-bound field and can
advance more than one day within its configured limits. It is not truncated by
the ordinary estimate cap. See [VN time passages](vn-time-passages.md) for units,
the 365-day bound, rejection rules and Living World catch-up.

## Characters and relationships

NPC history now prioritizes durable facts and changes instead of routine gestures.
Optional [memory and relevant recall](memory-rag.md) adds source-backed retrieval
and layered summaries, with background work deferred while the player is active.

The base VN social-continuity pass is separate from the optional **NPC Personality**
module. Its bounded Small/Utility-role call considers up to three present,
visible NPCs per player input. It proposes reactions based on personality and
established events. Private state includes trust, affinity, respect, tension,
recent memories and short-term intentions. By default, cards show only learned
facts and observable relationship descriptions. The optional **Character card
display** setting exposes evidenced relationship scores and the last evaluated
emotion. Private thoughts, intentions, goals and inventories remain hidden.

Durable relationship changes use the previous completed narrator message in the
same location, with evidence and message IDs. This deliberately introduces a
one-reply delay. The current player message can guide the immediate reaction, but
cannot establish a durable relationship fact by assertion. Repeated evidence is
deduplicated; compliments do not increase scores; positive changes have a cooldown.
Code bounds score deltas instead of accepting absolute model-assigned scores.
The same call reviews completed events separately from new reactions, so a new
question does not crowd out a previous conflict. An evidenced emotion can persist
without awarding relationship points. Reviewed narrator IDs prevent replaying it.

After three distinct meaningful events, an NPC is marked as a major character.
This does not create a duplicate entity and does not require affection: conflict
can also make a character important. NPC inventory remains private and transfers
stay under the existing world-continuity machinery.

The social model processes at most 64 characters, 12 recent memories per character
and 128 processed input IDs. It is a bounded continuity aid, not a complete
simulation of autonomous lives. Timeout or invalid output preserves valid state
and falls back to conservative narration. Model accuracy still matters: validation
cannot prove that every interpretation of a literary passage is correct.

Optional **Session settings → NPC Personality** adds selected NPCs' source-grounded
perception, decisions, review and tool access. Its Staged/Integrated workflows,
private notebooks and current-state inspection have their own settings and bounds;
the three-character social-pass limit is not the NPC Personality cast limit.
See [NPC decision workflows](npc-decision-workflows.md),
[private notebooks](npc-notebook.md) and [observable state](npc-observable-state.md).
NPC initiative remains subject to [world-action validation](npc-action-autonomy.md)
and never authorizes deciding for the player.

## Emotion palette and character thoughts

**Палитра эмоций** and **Мысли персонажей** are independent session display options
under **Session settings → Characters**.
They work with **NPC Personality** off, in observation mode or in live mode.
The same narrator reply supplies a dominant emotion and its intensity, and/or a
short fictional thought; there is no additional model request. When personality
appraisals are available, the narrator must respect them.

The palette colors the portrait by the NPC's overall state, not their attitude
toward the player. With thoughts enabled, hovering or focusing a portrait shows
the thought, and clicking opens the character card. Neither option rewrites older
replies. Missing, malformed or unassessed model output stays blank; the engine
does not infer a feeling from relationship scores or invent a thought. A rewritten
reply receives only its own valid assessment.

## Illustrations

Use **Illustrate this moment** on the latest completed narrator reply. Generation
uses the configured image provider, workflow and visual style. It creates a separate
illustration without replacing a location background or character portrait.

New VN replies capture their narration and public visible cast at completion.
Generating later uses that snapshot, not the current location or a character's
later possessions. The latest 100 snapshots are retained; generated image records
remain available. Messages without a matching snapshot cannot be illustrated.
An undone, deleted or edited message cannot receive the result of an obsolete job.

Snapshots include the public location, cast, known clothing, confirmed visible
conditions and scene-local placement. For ordinary sessions, preparation builds a
saved English visual plan from those frozen facts, audits it and compiles it for
the selected model family. A valid cached plan can be reused. Sessions with mature
content enabled use the existing source-based preparation path. These paths have
different logical request counts; they do not promise a single adaptation call.

Prompt preparation uses the Small / Utility role's configured deadline. Image
generation has the image provider's separate timeout. No preparation step loads
today's hidden inventory or fills an old moment from later state. Vocal delivery
cues remain available for narration/TTS rather than becoming visible objects.
See [current moment illustration paths](comfyui/README.md#moment-illustrations).

The narrator is explicitly constrained to approved NPC movements. These instructions
do not automatically repair an existing discrepancy between prose and engine state,
or invent a destination for a character whose whereabouts are unknown.

Existing provider/workflow limitations still apply. A scene description does not
guarantee perfect multi-character anatomy or identity consistency. This feature
does not install ComfyUI nodes or add a new identity-control workflow.

## Persistence and cost

VN preferences, private social state and illustration references live in the
session's versioned JSON state. They participate in save/load, checkpoint rewind,
session copying and ADS export/import. Copy/import remaps message evidence IDs and
illustration references; copied image assets are isolated from the original session.
No database migration is required for the base VN JSON preferences and social state.

NPC notebooks are an explicit exception to rewind: each NPC has one latest
document, retained across Undo and Chronicles rather than a history of notebook
versions. Copy/export/import use the notebook's own portability path.

Saving pace while a reply is being generated returns a busy response; save again
after the reply finishes. Turn and pace writes share a nonblocking session lease
in the standard single-worker server. Multi-worker deployments need shared
coordination; this lease does not serialize unrelated administrative edits.

A normal VN input can use continuity, the social pass for eligible characters,
narration and the shared completed-narration state check. NPC Personality, movement
confirmation, a bounded state-coverage correction and optional background services
can add requests. The social pass uses the configured Small / Utility role timeout,
not a fixed 45-second limit. Manual illustration has its own preparation and image
requests. See [turn latency](turn-latency.md) for the request boundaries and timings.

Automated tests use deterministic mocked models and image providers. They verify
contracts, mode isolation, ownership, persistence and failure paths; they do not
measure prose quality or establish that a particular local model is sufficient.

## Implementation map

- `backend/core/game_modes.py`: mode capabilities and normalization.
- `backend/engine/visual_novel/`: narration, tempo, continuity and private social state.
- `backend/engine/scene_illustrations/`: frozen moments and queued image generation.
- `backend/api/routes/adventures/vn_settings.py`: owner-only narration preferences.
- `frontend/src/components/game/VnNarrationSettings.vue`: pacing accordion.
- `frontend/src/components/game/VnMomentIllustration.vue`: manual illustration UI.

The narration contract draws on the preceding review of Japanese and other visual
novels: distinct character voices, selective detail, subtext, readable blocks and
player agency. It uses original instructions rather than copied game dialogue.

## Appearance and clothing

VN creation can enable detailed clothing independently of character-card indicators.
The player sheet has an Appearance tab; NPC private wardrobes remain hidden.
Outfits reference canonical possessions and change through grounded story actions.
See [Character appearance and clothing](character-appearance-and-clothing-plan.md)
for visibility, ownership, persistence and model limitations.
