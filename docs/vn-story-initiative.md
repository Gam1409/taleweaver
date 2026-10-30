# VN story initiative

Visual Novel turns can now include one autonomous action by a present NPC. The
existing Utility continuity request proposes the action alongside the player's
resolved contribution. There is no additional LLM call, background director loop,
new model dependency or database migration. Existing VN sessions use this path.
RPG and ordinary Chat turns retain their existing behavior.

The director receives a bounded premise and guidance, characterization and goals
for up to three present NPCs, and two recent attempted initiatives. The full story
frame remains available to the narrator. This increases input/output tokens in an
existing request; it is not zero-cost and production latency has not been measured.

## Player agency and scene rhythm

An NPC can start a relevant conversation, take an action within the current scene,
or depart through a known open exit without requiring a player invitation. The
player is never automatically moved or made to agree. Their next contribution can
redirect, interrupt, follow or ignore the NPC. Existing item-ownership rules still
apply to player descriptions: an invented possession is not automatically granted.

The continuity model classifies the scene as engaged, settling or open. Engaged
and settling scenes accept continuations of the current interaction; autonomous
departures and topic transitions require open plus an exact supporting excerpt
from the current input or latest narrator reply. Missing/malformed classification
blocks these transitions. Matching a quote proves its source, not the correctness
of the model's interpretation: semantic pacing still needs testing with real models.

Departure also requires a present, visible, undefeated, movable NPC, an allowed
destination and an open exit from the current location. Existing movement guards
run afterwards. Player movement and already-resolved NPC movement take precedence.
The narrator can show the approved departure but cannot continue dialogue with
that NPC after they have left, narrate unseen activities or assume the player follows.

## Continuity, repetition and retries

The narrator receives a final continuation reminder: respond after the latest
moment, develop the current interaction, avoid recapping unchanged scenery and
gestures, and prefer a short response over padding. Identical planner actions
(ignoring case, whitespace and terminal punctuation) from the last four attempts
are rejected. This does not remove generated sentences or guarantee elimination
of paraphrased repetition. Deliberate dialogue repetition and requested recaps remain
allowed.

Up to four attempted directions are stored under `__vn_story_direction__` in the
session JSON, associated with completed narrator messages. They are explicitly
planning history, not verified events, NPC journal facts or RAG memories. Incomplete
or empty responses do not record a direction. Normal game mutations use the existing
turn transaction; full Regenerate rewinds these directions and NPC movement with
the rest of the turn. Rewrite does not run the director or execute another movement.

Malformed optional initiative fields are discarded with an English warning while
valid continuity fields remain usable. No second repair request is introduced.

## Initial scope

This is immediate NPC initiative, not a complete simulation of off-screen lives,
a new chapter progression system or a random-event scheduler. NPC movement flags
in authored adventures remain authoritative. Actions are bounded to one observable
step; the system does not prewrite the player's future or guarantee an ending.
Current inventory, clothing, relationship and content-preference mechanisms remain
in force. Mature-content prompt text and insertion hooks are unchanged.

Regression tests cover allowed and rejected movement, player separation, emotional
scene protection, bounded planning history, optional malformed responses, the real
VN turn pipeline and full regeneration rollback. Those tests use deterministic
model doubles; narrative quality must also be evaluated in actual play.
