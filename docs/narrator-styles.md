# Narrator style

Choose **Adventure editor → Tone → Narrator style** to set defaults for new sessions. Choose **Session settings → Story & world → Narrator style** to change only the current session. Editing adventure defaults does not rewrite an existing session's frozen settings.

The optional literary voices are adapted from [jschm42/taleweaver at 012599eff](https://github.com/jschm42/taleweaver/blob/012599effc53f96c1e16191fcf2223cc39330b0f/backend/core/narrator_voices.py), under MIT. Examples include a campfire storyteller, noir detective, cozy fireside narrator, psychological thriller, sci-fi chronicler and gothic storyteller. The selector displays a short sample. **Custom narrator** allows a name and an instruction about diction, imagery and rhythm.

Literary voice, amount of narration and VN pacing have different responsibilities:

| Control | Effect |
| --- | --- |
| Literary voice | How the narrator writes: wording, rhythm and attitude. |
| Amount of narration | Flexible preference for brief, dialogue-led, balanced, detailed or expansive prose. |
| VN scene pacing | How events develop and when play pauses for a meaningful decision. |
| LLM role generation settings | Transport-level sampling and output-token budget. |

Both narrator controls initially use **Current narration**, adding no style instruction to legacy sessions. Selecting a voice adds only its bounded instruction, not its display sample or the entire catalog. There are no additional model calls and no new hard token cap. Detailed prose can naturally produce more output tokens.

The style hint reaches the narration pass. It does not change mechanics extraction or CHPM decisions, give an NPC knowledge they lack, alter approved state or make every NPC speak like the narrator. It also does not select an audio/TTS voice.

Settings persist through existing manifest/session JSON and adventure exports. They are copied with the adventure's session snapshot; no new database table or schema-version bump is needed. The server checks ownership and prevents session updates while a turn owns the write lease. Invalid values are rejected before the previous setting is replaced.
