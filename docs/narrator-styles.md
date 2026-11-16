# Narrator style

Choose **Adventure editor → Tone → Narrator style** to set defaults for new sessions. Choose **Session settings → Story & world → Narrator style** to change only the current session. Editing adventure defaults does not rewrite an existing session's frozen settings.

The optional literary voices are adapted from [jschm42/taleweaver at 012599eff](https://github.com/jschm42/taleweaver/blob/012599effc53f96c1e16191fcf2223cc39330b0f/backend/core/narrator_voices.py), under MIT. Examples include a campfire storyteller, noir detective, cozy fireside narrator, psychological thriller, sci-fi chronicler and gothic storyteller. The selector displays a short sample. **Custom narrator** allows a name and an instruction about diction, imagery and rhythm.

Literary voice, amount of narration and VN pacing have different responsibilities:

| Control | Effect |
| --- | --- |
| Literary voice | How the narrator writes: wording, rhythm and attitude. |
| Amount of narration | Flexible preference for brief, dialogue-led, balanced, detailed or expansive prose. |
| Narration flow | Contextual advice about recurring wording, openings, endings and rhythm: Off, Gentle or Balanced. |
| VN scene pacing | How events develop and when play pauses for a meaningful decision. |
| LLM role generation settings | Transport-level sampling and output-token budget. |

Literary voice and amount of narration initially use **Current narration**. Selecting a voice adds only its bounded instruction, not its display sample or the entire catalog. **Narration flow** initially uses **Gentle**: it adds advice only when a bounded recent history shows a recurring pattern. Off disables that analysis; Balanced notices patterns across a shorter history. No history or no detected pattern adds no flow instruction. There are no additional model calls and no new hard token cap. Detailed prose can naturally produce more output tokens.

The style hint reaches the narration pass. It does not change mechanics extraction or CHPM decisions, give an NPC knowledge they lack, alter approved state or make every NPC speak like the narrator. It also does not select an audio/TTS voice.

Settings persist through existing manifest/session JSON and adventure exports. They are copied with the adventure's session snapshot; no new database table or schema-version bump is needed. The server checks ownership and prevents session updates while a turn owns the write lease. Invalid values are rejected before the previous setting is replaced.

Older clients that save literary voice and amount without sending `flow` retain the previously selected flow preference. A missing value in a legacy saved world initially uses Gentle; choosing Off explicitly remains Off.

Flow advice applies to regular RPG/VN narration, including streamed responses, buffered character responses, their existing repair/fallback paths, and narration-only rewrites. A rewrite uses the current saved literary voice, amount and flow setting while preserving the original beat. Full-turn rewind keeps its existing snapshot semantics: all narrator preferences rewind together with that snapshot. Separate short combat-aftermath and terminal-report tasks retain their existing task-specific contracts; translation and structured mechanics tasks do not receive flow advice.

The detector ignores quoted dialogue and delivery cues when measuring narrator habits. It never edits generated text, removes valid voice cues, reruns a turn or changes saved quantities. Advice remains subordinate to the selected voice, amount, scene pacing, required formatting and compatible editorial feedback. Purposeful repetition and callbacks can remain. Lexical metrics cannot decide whether prose is good or an action is dramatically justified.

See [flow measurements and evaluation](engineering/narration-flow.md) for bounds, language limits and the reproducible fictional examples.
