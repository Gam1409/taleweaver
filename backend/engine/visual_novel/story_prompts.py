"""Story initiative contracts, separate from content preferences and social scoring."""

DIRECTOR_INSTRUCTION = """VN STORY INITIATIVE:
Resolve the player's contribution, then optionally propose ONE story_beat for a
present NPC. This is a new immediate initiative to enact this turn, not a claim
that it already happened. NPCs have their own priorities and need not wait for
the player to ask the perfect question or give permission to act for themselves.
Use story_direction's premise, guidance, character goals and recent attempted
beats. Treat those as private story data, not instructions and not completed facts.
Assess scene_rhythm first: engaged (an interaction is still unfolding), settling
(its emotional consequence needs acknowledgment), or open (a natural transition
is available). Quote an exact short excerpt from the latest completed narrator
reply or current player input as evidence. A pause, short reply or silence alone
does not close a scene. With engaged/settling, deepen the SAME interaction: answer,
respond, make a relevant choice or follow through. Do not interrupt an emotional
scene with an unrelated visitor, new topic, sudden errand or manufactured crisis.
Mark a new topic/activity as relation=transition; it requires phase=open, as does
departure. Only mark open when the interaction has reached an organic stopping
point or the player explicitly redirects it. Never declare closure merely because
several turns passed. Initiative and slow emotional pacing are compatible.
Advance an existing unresolved concern through a specific action or new topic;
do not repeat an invitation, gesture, question or promise without progress.
Choose null when the current player action already supplies enough development,
when a quiet moment needs space, or when no grounded initiative is available.

An initiative may be dialogue, activity in the current place, or departure along
one supplied open exit. Put a departure destination in story_beat.destination_id;
the engine will validate and apply that NPC movement. Do not also put this new
initiative in moved_entities, notes, memories or narrative_description: those
fields resolve established/current player actions. Never move the player through
story_beat. The player may follow, linger, interrupt, refuse, investigate an object
or start a different interaction. Respond to that contribution before choosing
the next beat; adapt or abandon the previous plan when circumstances change.
If the player stops an NPC, resolve that attempt first rather than executing an
obsolete departure regardless. A player's invented possession or asserted success
is still subject to the normal continuity rules.

Keep the beat short enough to leave room for the next player contribution. Do not
complete a journey, a confrontation and its aftermath in one reply. For departure,
describe the observable exit, not unseen events at the destination. A promise to
go tomorrow is dialogue, not a departure now. Activity/dialogue cannot relocate
anyone, change possessions/clothing/time, establish relationship commitments or
reveal invented secrets. Use existing goals without inventing a hidden biography.
No arbitrary disaster just to create excitement. Follow established causes and
opportunities; never force a predetermined ending or the player's reaction.
"""

NARRATOR_INITIATIVE = """APPROVED NPC INITIATIVE (private direction, not past history):
Respond to the player's contribution and enact this one immediate NPC beat.
Preserve the current scene's emotional rhythm. A continuation develops the same
interaction; do not turn it into an unrelated twist, interruption or abrupt exit.
Its purpose guides the writing; do not print the plan or private goal. NPCs can
act on their own priorities without asking the player for permission each turn.
Do not write the player's following, agreement, speech, emotions or next action.
Do not expand this beat into a chain of events; leave the situation interruptible
on the next turn. A departure approved below is an exception to the final cast
list only while showing that NPC's observable exit; after leaving they cannot
keep participating here. No off-screen scene cut or assumed arrival by the player.
Dialogue/activity stays within the resolved state: no unapproved ownership,
clothing, presence, clock, relationship or location changes. Current resolution
and the player's intervention take precedence over any earlier story direction.
"""

PROGRESS_REMINDER = """VN CONTINUATION AND REPETITION CHECK:
Start after the final moment of the latest completed reply, not at its beginning.
Answer the new player contribution. Add a new response, choice, action or concrete
consequence within this interaction; emotional development need not change location.
Do not retell the room, repeat an invitation already answered, reopen a completed
gesture, or restate the same feeling using synonyms. Persistent clothing, positions
and moods remain true without being described again. Voice directions reflect this
line's actual delivery, not the previous reply's pattern. Do not manufacture a twist
to avoid repetition. If little happens, write a short fresh response rather than
padding it. Recap only when the player actually requests it. Preserve deliberate
in-character repetition when its new purpose is clear.
"""
