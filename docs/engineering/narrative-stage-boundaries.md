# Narrative stage boundaries

The existing pipeline separates world resolution, NPC message selection and prose.
These are ownership boundaries inside the current requests, not extra agents,
model calls, state stores or a new scheduling framework. KV-cache policy is unchanged.

## Independent state owners

| Concern | Existing owner | Contract |
| --- | --- | --- |
| Clothing | `clothing` and canonical worn profiles | Validate coverage, placement and dressing against known possessions. |
| Inventory | Existing possession/continuity and narrated-item handlers | Preserve item IDs, owners and unrelated contents. |
| Emotion glow | `npc_presentation` | Narrator-authored overall emotion/intensity, bound to the published reply and its opt-in. |
| Scene description | World movement, `scene_continuity` and `scene_staging` | Retain environment, processes and confirmed positions with their existing evidence rules. |
| Thought bubble | `npc_presentation` | Independently enabled narrator-authored UI thought; not a psychological memory write. |
| Image workflows | Existing image tasks/presets and illustration snapshots | Render the selected snapshot with the configured workflow; no ownership of NPC decisions. |
| NPC Personality | `chpm` | Select private NPC message meaning from accessible experience and authored identity. |

Owners exchange canonical IDs and confirmed facts. Personality can inform a decision
to request an action; it does not independently grant a transfer, change clothing,
move an actor or rewrite an image workflow. Clothing, possessions, snapshots and
portrait options continue to operate with Personality off, shadow or live.

## World request

VN progression resolves physical outcomes, time, access, possessions and movement.
It no longer advertises or forwards the model's `narrative_description`. Legacy
responses containing that field are ignored. Host-generated rejection/resolution
descriptions still reach narration; RPG/Chat keep their own unchanged contracts.

The optional world `story_beat` is a movement projection with an NPC ID and destination.
It cannot carry an alternative dialogue answer or preference through free purpose/
action text. The existing departure eligibility, exit and presence checks still
apply, and the player is not moved by an NPC departure. Saved historical StoryBeat
records remain readable; new requests do not replay them as completed actions.

Scene focus remains bounded provisional orientation, not a completed event or an
answer the NPC must give. New personal details belong to the active narrative owner.

## NPC message meaning

The live proposal exposes `message_plan` as the wire name of the existing bounded
`Intent.intention` field. It asks for the concrete intended answer, stance or proposal,
including any newly chosen harmless personal detail needed for that answer. It is
a private meaning plan, not prescribed dialogue wording or a physical world update.
Generic labels such as “share a preference” leave the actual preference undecided.

There is no duplicate response-content ledger. Canonical candidates, previous
intentions, decisions, narrator contracts and saved history still use `intention`.
The local wire parser accepts the legacy name; conflicting old/new names are rejected.
Existing length limits and stored schema versions are unchanged.

The shared review receives the original player request as untrusted story input
alongside the selected plans, host outcomes and proposed prose. Its preflight uses
that same payload for the existing request budget. Review checks the response's
meaning and facts without selecting a different substantive answer for the NPC.
Literary expression, emotional pauses, voice and ordinary gestures remain free.

A new personal declaration becomes source-bound accepted speech through the existing
memory path. A planning draft alone is not biography, shared history, inventory or
confirmed knowledge. No new personality traits are silently written from a plan.

## Mode routing

| Mode | Owner of response meaning |
| --- | --- |
| Off | Ordinary narrator; no CHPM planning request or contract is added. |
| Shadow/Observe | Ordinary narrator; computed CHPM proposals stay out of its context. |
| Live/Enabled | Selected NPC message plans; ordinary narration remains responsible for uncontrolled NPCs. |
| Partial | Accepted peers keep their plans; deferred controlled NPCs retain the existing inactive-story boundary. |
| Simplified/replacement | Ordinary narrator with confirmed identity/history/world context; unused or rejected plans are not copied into the replacement. |

Portrait thoughts and emotions remain independent UI assessments, including for a
deferred NPC. Inner experience remains optional context: a supplied `sexual_desire`
estimate retains its level, reason and freshness. A missing or historical estimate
does not become zero, and no qualitative estimate is automatically mapped to a UI color.

## Verification limits

Offline tests inject competing world drafts and message plans, then check actual
turn routing, review input, persistence, accepted speech sources, recovery and
independent clothing/portrait/snapshot behavior. These verify ownership and transport,
not that a real model always chooses a sufficiently concrete or emotionally credible
plan. Existing semantic review remains fallible. Live evaluation is still paused.
