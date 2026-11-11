"""Physical events share the existing post-narration extraction request."""

INSTRUCTIONS = """
PHYSICAL CONDITIONS: condition_updates is a small list of changes proved by completed_narration.
Use only current subject IDs in actors/items and exact condition IDs in physical_conditions.
To record a NEW injury, contamination, fluid trace, pain or other explicit bodily condition,
use operation=record with target_id, kind, part and short neutral intrinsic detail.
Use kind=other for physical signs such as trembling or flushed skin, not emotions or intentions.
The server assigns its condition ID.
Record a bodily condition still present at the end of this narration, including temporary
conditions. A completed fleeting gesture or a single vocal cue alone is not an ongoing condition.
Item placement, clothing and poses use their existing sections; record only their explicitly
established bodily consequences here, not a duplicate inventory or pose entry.
For an existing condition use only condition_id: change updates its detail without clearing it;
treat keeps an injury/pain as treated; reduce keeps a partial remaining condition;
clean removes contamination/fluid; heal resolves an explicitly healed injury/pain;
remove resolves explicitly eliminated contamination/fluid/other. Never clean a wound into nonexistence.
A wiped surface does not empty an internal region. Stitching/disinfection is treatment, not healing.
Record an internal condition and an external trace separately when both are explicitly established;
each uses its own part and evidence. A change to one does not automatically change the other.
Fluid, wetness, dirt and bodily traces are neutral physical facts, not feelings or personality traits.
An emotional label alone does not prove a bodily sign; a bodily sign alone does not prove a desire.
Do not infer pregnancy, diagnoses, quantities, undress or any new consequence not explicitly established.
For the same subject/kind/part reuse the active condition ID. Never restate all unchanged records.
Private is the default visibility. Public means established openly observable/shared scene information.
A condition known only to the player and particular participants remains private. The player's
knowledge alone does not make it public; mere co-presence does not prove another NPC noticed it.
Internal anatomy alone does not decide visibility either. When access is uncertain, keep private.
This flag does not establish current visual exposure or any particular NPC's knowledge.
Each operation needs an evidence reference to THIS completed narration, not the player's
request, old history, dialogue claims, imagined outcomes or a recalled earlier event.
A full cleaning affects only that identified garment/part; a partial cleaning uses reduce.
Do not resolve conditions merely because they were not mentioned. Return [] when no change is proved.
Leave unsupported candidates out; the host retains existing facts. Use at most 12 proposals.

VISUAL SURFACE EVIDENCE: public information does not by itself prove visual exposure.
visual_detail is optional and must copy an EXACT short visible surface phrase from evidence;
visual_region is the corresponding clothing coverage region (head includes neck, torso,
arms, pelvis, legs, feet, hands). Supply both only when completed_narration directly
establishes that this trace is currently externally visible. Never infer exposure from an
injury, pain, internal fluid, emotion or a public visibility label. Preserve current clothing.
Empty visual_detail means no confirmed image surface; the physical condition still persists.
For a visible garment trace use that garment's canonical item ID, never the wearer's skin.
On change/treatment/reduction, re-confirm the still-visible surface with this response's
exact quote if available; old visual evidence is not silently carried across a changed state.
A current explicit visual observation can refresh an existing condition using change and
its resulting current detail, without creating a duplicate or implying healing/cleaning.
"""
