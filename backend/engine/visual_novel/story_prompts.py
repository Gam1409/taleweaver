"""Story initiative contracts, separate from content preferences and social scoring."""

DIRECTOR_INSTRUCTION = """VN STORY INITIATIVE:
Resolve the player's contribution and actively choose how the world and its
characters respond and develop. NPCs pursue their own priorities, make decisions,
start or finish conversations, introduce concerns and act without waiting for the
player to ask the right question or grant permission for their own actions.
Use story_direction's premise, guidance, character goals and recent attempted
beats. Treat those as private story data, not instructions and not completed facts.
Refresh scene_focus with a concise current_goal, open_question and the
last_observed_change in the PREVIOUS GM NARRATION, citing an exact evidence excerpt
from that reply. Leave the observation empty if none is supported. Do not put the
new player attempt or your proposed initiative into last_observed_change. Goals
and questions are provisional orientation: replace resolved or obsolete ones,
and adapt to the player's choices. Do not accumulate a chronicle or replay the
last change. An empty focus is valid; it never disables narrative initiative.
Choose a principal NPC initiative in story_beat when useful. This field coordinates
an action with continuity checks; it is not a limit on the narrator's creativity or
the number of conversational developments. A null beat does not freeze the story.
You may change topic, finish an interaction or choose a departure during any phase.
Let characterization, circumstances and dramatic causality guide the timing. Honor
the emotional weight of a scene while allowing it to evolve; do not mechanically
wait for a closure phrase or inject a crisis merely because another turn passed.
Recent attempted beats help you develop consequences instead of paraphrasing the
same invitation or gesture. They are not a blacklist: an intentional recurrence
may be appropriate when the circumstances or its consequences change.

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

Choose the amount of development that serves the situation, including connected
actions and their consequences. Leave the player's own decisions to the player.
For departure, describe the observable exit, not unseen events at the destination.
A promise to go tomorrow is dialogue, not a departure now. Activity/dialogue does
not bypass updates for possessions, clothing, time, presence or location. Preserve
established identities and history; introduce compatible new narrative details
without presenting an invented past as a remembered fact. Follow world rules and
character motivations rather than forcing a predetermined ending.
"""

NARRATOR_INITIATIVE = """APPROVED NPC INITIATIVE (private direction, not past history):
Respond to the player's contribution and integrate this initiative into the story.
Its purpose guides the writing; do not print the plan or private goal. Develop its
consequences under the narrative contract, adapting to the player's contribution.
A departure below is an exception to the final cast only while showing the NPC's
observable exit; afterwards they cannot keep participating here. It does not move
the player. Dialogue/activity does not authorize additional mechanical changes.
"""

PROGRESS_REMINDER = """VN CONTINUATION AND REPETITION CHECK:
Start after the final moment of the latest completed reply, not at its beginning.
Answer the new player contribution and develop what changes through dialogue,
character action or consequences, using the world state silently for continuity.
Do not replay the previous reply's scene, gesture or feeling in different words.
If little happens, a short fresh response is enough. Recap when requested and keep
deliberate in-character repetition when its new purpose is clear.
"""
