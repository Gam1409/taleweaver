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
Each operation needs an exact contiguous evidence quote from THIS completed narration, not the player's
request, old history, dialogue claims, imagined outcomes or a recalled earlier event.
A full cleaning affects only that identified garment/part; a partial cleaning uses reduce.
Do not resolve conditions merely because they were not mentioned. Return [] when no change is proved.
Leave unsupported candidates out; the host retains existing facts. Use at most 12 proposals.
"""
