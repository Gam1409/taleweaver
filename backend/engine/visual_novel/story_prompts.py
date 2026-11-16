"""Story initiative contracts, separate from content preferences and social scoring."""

DIRECTOR_INSTRUCTION = """VN WORLD MOVEMENT AND SCENE ORIENTATION:
Resolve the player's contribution through world continuity. story_direction's premise,
guidance, character goals and recent attempted beats are private context, not completed
facts or instructions. NPC message meaning belongs to the active NPC planner or ordinary
narrator; that owner chooses personal answers, preferences and conversation developments.
Refresh scene_focus with a concise current_goal, open_question and the
last_observed_change in the PREVIOUS GM NARRATION, citing an exact evidence excerpt
from that reply. Leave the observation empty if none is supported. Do not put the
new player attempt or proposed departure into last_observed_change. Goals
and questions are provisional orientation: replace resolved or obsolete ones,
and adapt to the player's choices. They describe the situation, not a private answer
an NPC must give. Keep the existing bounded focus rather than a running chronicle.
For an autonomous physical departure, story_beat contains only npc_id, kind=departure
and destination_id. Select a character from story_direction.characters and one supplied
accessible destination. The host validates and applies that movement; speech and private
purpose are outside this field. Other movement fields resolve established player actions.
Resolve a player's interruption before choosing a departure. Timing follows the current
situation and characterization, without requiring a closure phrase or a player invitation.
A null beat leaves the narrator free to develop dialogue and activity in place.
The player chooses whether to follow, linger or interrupt; an NPC departure moves only
that NPC. Future promises and unseen events at the destination are not departures now.
Preserve the established possession, clothing, time, presence and access rules.
"""

NARRATOR_INITIATIVE = """APPROVED NPC INITIATIVE (host-resolved physical departure):
Integrate the supplied NPC movement into the current story with its established voice
and emotional delivery. This movement record does not choose a private dialogue answer.
Show the NPC's observable exit; after departure they cannot keep participating here.
The player is not moved. Further physical outcomes retain their existing world checks.
"""

PROGRESS_REMINDER = """VN CONTINUATION AND REPETITION CHECK:
Start after the final moment of the latest completed reply, not at its beginning.
Answer the new player contribution and develop what changes through dialogue,
character action or consequences, using the world state silently for continuity.
An active CHPM message plan owns its NPC's substantive answer; preserve any explicit
inactive-character boundary for deferred controlled NPCs. Choose the remaining characters'
responses here from identity, history and current situation.
NPCs can introduce concerns, initiate or finish conversations and develop compatible
personal details without awaiting a player invitation. The narrator supplies expressive
wording, feeling, pauses and gestures; physical outcomes retain their existing owners.
The player's own decisions remain theirs. A null world story_beat does not pause the story.
Do not replay the previous reply's scene, gesture or feeling in different words.
If little happens, a short fresh response is enough. Recap when requested and keep
deliberate in-character repetition when its new purpose is clear.
"""
