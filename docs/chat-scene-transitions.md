# Chat scene transitions

Chat progression proposes `new_scene_id` using the Small/Utility role. The engine
accepts only a connected, available exit (including valid unlocks); deterministic
lock and world-state guards still run before the state change is applied.

Previously, an additional guard required English/German movement words and
normalized destination names to ASCII. Correct Russian and other non-Latin
movement proposals could therefore be discarded even after positive LLM intent
classification.

The confirmation now passes the proposed destination and map context to the
existing Small/Utility intent call. Its response must confirm immediate movement,
return the exact proposed map ID, and quote the action from the player's message.
It does not require a language-specific verb list or an exact grammatical match
between the player's destination wording and the scene label. Missing/invalid
confirmation fails closed. This replaces the existing confirmation call rather
than adding a call to every turn.

Narration receives an explicit state-derived location result on every turn:
previous scene, current scene, and whether the scene actually changed. This takes
precedence over the player's desired outcome and the mechanics draft. A rejected
or omitted movement must not be narrated as arrival or justified by invented locks.

This fixes a deterministic language restriction; it does not make LLM interpretation
infallible. If the first mechanics pass omits `new_scene_id`, no movement is applied.
No new scene is created from narrative text, and no map restrictions are bypassed.
The new confirmation schema is tested with mocked model responses and full chat
turns; live model compliance still needs gameplay verification.
