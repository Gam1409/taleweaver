"""Physical events share the existing post-narration extraction request."""

INSTRUCTIONS = """
PHYSICAL CONDITIONS: condition_updates is a small list of changes proved by completed_narration.
Use only current subject IDs in actors/items and exact condition IDs in physical_conditions.
To record a NEW injury, contamination, fluid trace or pain, use operation=record with target_id,
kind, part and short neutral intrinsic detail. The server assigns its condition ID.
For an existing condition use only condition_id: change updates its detail without clearing it;
treat keeps an injury/pain as treated; reduce keeps a partial remaining condition;
clean removes contamination/fluid; heal resolves an explicitly healed injury/pain;
remove resolves explicitly eliminated contamination/fluid/other. Never clean a wound into nonexistence.
A wiped surface does not empty an internal region. Stitching/disinfection is treatment, not healing.
Fluid, wetness, dirt and bodily traces are neutral physical facts, not feelings or personality traits.
Do not infer pregnancy, diagnoses, quantities, undress or any new consequence not explicitly established.
For the same subject/kind/part reuse the active condition ID. Never restate all unchanged records.
Private is the default visibility. Public means established public information, not permission to reveal
private details to another character. Do not infer current visual exposure from this flag.
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
