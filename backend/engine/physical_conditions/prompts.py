"""Physical events share the existing post-narration extraction request."""

INSTRUCTIONS = """
ITEM STATE: Use condition_updates kind=item_state for a known item's changed contents,
inscription, supply, cleanliness, form or another explicitly established mutable property.
Known items include items and the optional item_state_targets catalog. The latter contains
visible state-only subjects; it never authorizes transferring, consuming or creating an item.
part is an extensible stable lowercase property key (letters, digits, underscores; 80 max),
not a value. Examples: contents, fill_level, wetness, temperature, charge, sharpness.
Inspect existing item_state records first. Reuse their condition_id for the SAME property,
even when wording or language changes. Never create synonymous properties for one fact.
Keep independent properties separate; fullness does not describe the kind of contents.
Do not enumerate unobserved properties or fill in defaults from common knowledge.
Existing physical condition records remain authoritative too. Do not restate their
same fact as another property. When a completed change explicitly resolves an existing
trace, update that record with its supported operation; do not leave a contradictory trace.
Keep the existing item ID, intrinsic description, ownership, placement and artwork.
Use record only for a new dimension, then change with its existing condition_id.
Never create a replacement item because it became full, empty, dirty, clean, creased,
smoothed, written on or depleted. These are current states, including negative states;
do not resolve/remove them. Each dimension is independent: cleaning does not smooth it.
Use a short EXACT excerpt as detail, from evidence (or player_evidence when supplied).
Preserve its original grammatical case, gender, number and language. Never normalize
the value or rewrite it to agree with the item's name. For example, from
"Коробка осталась открытой" copy detail="открытой", not "открытая" or "открыта".
Partial states such as half full or a little water remaining are valid. Record exact
amounts only when explicitly established; never calculate an unknown remainder.
Contents and supplies here are descriptive facts, not another inventory. Existing
separately identified components still require their canonical transfer/consumption
contracts. Do not delete a container when its contents are used up or duplicate them.
State-only changes need no item action. Never copy obsolete intrinsic-state prose over
current saved state. Omission leaves every dimension unchanged.
PLAYER REPORTS: player_report is the current saved user turn, not confirmed world truth.
It can supply an item fact only after authoritative_resolution and completed_narration
accept it under the world's rules. Questions, intentions, hypotheticals, denied actions
and assertions contradicted by the completed outcome are not accepted facts.
Optionally set player_evidence to an exact, unique excerpt of player_report and detail
to an exact excerpt of it. Still cite completed_narration in evidence as confirmation
of that result. Without such confirmation, retain saved state and omit the update.
Only item_state supports player_evidence; leave it empty for other physical conditions.
For multiple changes to one dimension, use source order and a distinct occurrence for
each change. The final accepted state supersedes earlier states; do not restate unchanged facts.

PHYSICAL CONDITIONS: condition_updates is a small list of changes proved by completed_narration.
Use only current subject IDs in actors/items and exact condition IDs in physical_conditions.
Resolve synonyms, colloquial wording and literary references through the full context and
known subject IDs. An established current result need not use a formal status word or an
action verb. Figurative emotional language alone does not establish a physical change.
Keep the original evidence; item-state detail still copies an exact contiguous excerpt.
For a NEW explicitly established anatomical condition, prefer stable part IDs such as
clitoris, labia, vagina, anus, sphincter, uterus, penis or testicles when applicable.
Existing same-fact records keep their condition_id and part across wording changes.
These identifiers classify an established fact; they never establish anatomy by themselves.
To record a NEW injury, contamination, fluid trace, pain or other explicit bodily condition,
use operation=record with target_id, kind, part and short neutral intrinsic detail.
Use kind=other for physical signs such as trembling or flushed skin, not emotions or intentions.
The server assigns its condition ID.
Record a bodily condition still present at the end of this narration, including temporary
conditions. A completed fleeting gesture or a single vocal cue alone is not an ongoing condition.
Describe its resulting current state, not a retelling of the action that caused it.
Review existing records before adding a new sign. When the completed outcome explicitly
ends an earlier transient reaction or a record that merely duplicated now-ended contact
or item placement, resolve that existing ID with the applicable operation and current evidence.
Do not retain a completed past event as current pain or another bodily condition merely
because it mentions a body part. Omission alone still does not prove recovery or cleaning.
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
