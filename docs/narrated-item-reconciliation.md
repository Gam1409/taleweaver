# Completed narration and possessions

VN turns reconcile item actions after completed narration and before scene staging and illustration snapshots. This uses one bounded Small-role request with that role's configured deadline. Ordinary narration can stream before the check; reviewed NPC narration waits for validation and the completed state transaction. Incomplete narration is never used. General guardrail rejection blocks state reconciliation; a localized canonical item denial can still admit unrelated state for known accessible targets. Failures produce a system notification rather than claiming inventory was updated.

Shared extraction validates each item proposal with the existing strict item
contract. Valid proposals keep their original indices for deterministic item IDs
and placement references when another proposal is invalid. A denied subject, or a
room-level proxy for it, cannot be restored through independent state updates.
The original physical/scene validators still check evidence, ownership, audience,
operations and game time. Rejected independent updates are counted and reported.

The local response parser now preserves independent sections with staging both
enabled and disabled. With staging disabled, the wire schema and instructions
still omit staging; the tolerant parser does not enable that feature. Each item
candidate is revalidated against the original strict contract before any state
is applied. A malformed item cannot discard an unrelated valid scene/body section.

The active request schema requires explicit `actions`, `condition_updates`,
`scene_updates` and `final_frame_actions` arrays. Enabled staging also requires its
root field and `changes`, `props`, `explicit` lists. Local/saved constructors retain
their compatible defaults. The runtime records which sections were actually
provided before defaults and source binding can erase that distinction.

A missing section is unconfirmed, rather than an explicit empty result. The
existing debug ledger records `response_sections` and `unconfirmed_sections`,
and the overall check needs review. Independent valid sections are retained;
missing body checks preserve conditions, missing final actions have no confirmed
frame, and incomplete staging retains valid independent sections. A missing pose
section leaves poses unconfirmed; missing prop checks make old placements
provisional; missing explicit-act checks do not certify absence of an act.

The same extraction request also classifies every source group in `coverage`:
items, conditions, scene and enabled staging can overlap; unchanged, historical
and uncertain are exclusive. Up to 24 groups retain references to all original
fragments. A group marked with a changed domain needs a matching source-bound
proposal in that domain. Historical and uncertain groups cannot authorize new
state changes. Diagnostics distinguish missing annotations from explicit empty
results; independently valid sections survive malformed annotations.

These checks expose inconsistent or incomplete extraction, not every semantic
omission. A model can still misclassify a changed fragment as unchanged or miss
one of several events in a group. Exact occurrence references keep a current
event separate from later recollections using identical words. No additional
model call or story-text editing is introduced.
The standalone staging fallback uses the same required lists and completeness
checks before defaults are applied.

Handled partial responses also retain their processed input ID. Repeating the
same handled check cannot apply accepted inventory changes twice or invalidate
confirmed staging merely because a response section was missing. Prose-only
regeneration preserves committed outcomes; a full turn replay uses its existing
before-turn rollback rather than reapplying partial effects.

These checks establish response completeness, not semantic extraction recall.

The existing request also supplies `extraction_limits.condition_updates` from the
canonical twelve-operation limit. The model should reuse existing IDs, avoid
unchanged/repeated descriptions and prioritize completed resolutions and lasting
state. Distinct lifecycle transitions still require their own evidence. Limits,
saved fact capacity and the number of model requests are unchanged.

At full capacity, `conditions_deferred` marks groups with additional established
changes that could not fit. It can coexist with other changed domains or with
`conditions` for a partially handled group. It is invalid below capacity and can
never mark a turn complete. The audit records the limit, proposed count and deferred
groups; saturation without an explanation remains a missing-proposal warning.
The turn displays a review notice even when every response section was present.
Confirmed independent proposals are retained. Deferred groups are not applied,
treated as unchanged, automatically retried or placed in a new background queue.

An explicit empty array may still miss a narrated event; an exact quote may still
be a negation, recollection or claim. Paired scene and physical-condition gold
cases exercise literal/literary/Russian events, unchanged controls, another owner's
garment, treatment versus healing, partial cleaning and repeated occurrences.
They score missed and false updates independently of a model's “all checked” claim.
Mocked output verifies host behavior; live-model recall remains unmeasured here.

Existing items retain IDs and gameplay metadata. Transfers remove the previous owner's inventory, worn reference and equipment reference, then update the recipient. Receiving or holding does not equip the item. Wearing needs existing appearance and valid garment metadata. Each action is validated against copies before any changes are stored. Reprocessing the same input message is a no-op.

Completed narration can update the existing worn garment's `uncovered_regions`.
Partly lowered or partly donned clothing remains `worn`; it is not a completed
removal. Null or omitted placement preserves known coverage, while an explicit
empty array restores normal coverage. Regions must belong to that garment's
coverage. Existing ownership, appearance, detailed-clothing and age checks apply.
Debug recovery retains its separate, evidence-bound outer placement fields.
An existing garment can require a displacement correction even when its ownership
and worn record are complete. An otherwise identical reviewed placement refreshes
missing or stale source identity, content hash, quote or role; an already matching
proof remains a no-op. No garment is recreated and preview/apply still require
explicit selection, unchanged history and the original evidence/ownership checks.

Prefer a final outcome per item. Multiple proposals for one existing ID can form
an atomic chain, such as removal followed by handover, when completed actions have
continuous ownership and unique, non-overlapping quotes in narrative order.
An invalid step rejects that item's whole chain; unrelated items remain eligible.
Schema-invalid peers also block a partial chain. Original action indices remain
stable for generated IDs and scene-prop references. Interleaved actions on different
items retain their original global order. A final transfer already
applied by mechanics is not replayed through intermediate ownership states.

The extraction request supplies the current narration as an ordered passage map,
reusing the existing NPC-review source index. Evidence selects a request-scoped
`narration:<scope>:pN` reference; room-only facts may select `room:<scope>:pN`.
The host resolves it to the exact current text
before ordinary validation and persistence. Literal quotes remain supported;
unknown references, paraphrases and combined fragments are not repaired. No extra
model request or duplicate copy of the narration is added. The same source
catalogue binds physical, scene, item and optional staging proposals.

Passage references prevent transcription mistakes; they do not prove that the
chosen passage establishes the proposed event. Figurative prose, intentions,
memories and unresolved pronouns still require correct model interpretation.
An ambiguous metaphor alone must not be treated as established clothing removal.

An explicitly established ordinary object or garment without a canonical ID can become an inline inventory card. The schema cannot grant bonuses or effects. Descriptions must preserve known facts and leave unknown details unspecified. New underwear requires detailed clothing and an established adult source owner (or adult recipient for a scene acquisition). These gates do not infer age from prose.

Every proposal needs an exact quote from the completed response, valid participant IDs and a completed-action classification. Semantic interpretation still depends on the model: quote matching alone does not prove transfer or consent. The private `__narrated_items__` ledger stores accepted changes, rejected reasons, source input-message ID and narrative hash. Session replay/checkpoints preserve the state transactionally; newly materialized dropped objects retain runtime provenance for checkpoint cleanup. Regeneration remains a prose rewrite preserving committed outcomes, not a second transfer.

The current reconciler covers acquisitions into actor inventories, actor-to-actor transfers, removal and wearing. Scene drops, consumption, locked-container access and gameplay rewards continue through the existing mechanics pipeline. Existing past messages are not retrospectively mined for possessions. Inline cards do not require image generation.

The pre-narration clothing planner can also use the latest completed same-scene narration as evidence that a present giver has a previously described garment. A current player assertion alone cannot establish that source.

Unregistered cosmetic acquisitions proposed before narration are deferred rather than rejected solely for a missing ID. They are not possessions until completed narration passes reconciliation. Known objects, including inventories of absent NPCs and inaccessible containers, retain ordinary ownership validation. Mechanical rewards are not eligible for this deferral.

The session header exposes **Item and travel checks** to the session owner. It shows the latest persisted item result, rejected actions or failure category, and confirmed local-arrival companion results. It explicitly identifies sessions outside VN mode, where this item reconciler does not run. Results describe the latest check, not a complete history.

Rejected item actions distinguish an incomplete action basis from a quote that does not occur exactly in the completed narration. **Rejected proposal details** preserves the proposed basis and quote for each of the existing maximum six actions, including quotes at the 800-character limit. These are rejected model proposals, not confirmed story facts. Inspection makes no model request. Older saved checks retain their original error text and show no invented proposal details.

The live new-item wire contract distinguishes ordinary objects from clothing by
`kind`. Clothing requires garment metadata and at least one wearable slot in both
JSON Schema and host validation; ordinary items cannot carry clothing metadata.
Existing valid payloads keep their data shape. Invalid responses retain up to five
safe field paths and constraint explanations for owner inspection. Older failed
checks expose their recorded field paths without inventing missing explanations.
Diagnostics exclude raw model inputs, unknown custom error messages and provider
text. Schema-invalid item proposals and dependent chains are rejected while
independent valid proposals remain eligible. Failures do not infer garment data
or dispatch another model request.

Skipped checks distinguish an earlier rules/ownership rejection from narration exceeding the existing 16,000-character limit. The saved reason and system notification retain known host rejection details; unexpected internal errors use a safe generic explanation. Length failures report the actual character count and unchanged limit. The boundary is inclusive, no narration is truncated, and no extra model request is dispatched. Turn-local rejection details cannot carry over to a different input, while the completed check remains in the normal saved session state. Older generic warnings cannot recover details that were not recorded.

Dynamic-location confirmation includes currently present NPCs and evidence for co-arrival from the current action. Confirmed companions are bound to the server-created destination ID before normal movement validation. Stationary NPC and access restrictions still apply; recorded results distinguish moved, not moved and rejected companions. This does not retroactively relocate NPCs based on unsupported assertions.

Explicit current worn-garment descriptions now use `observed_wear`. They must cite the completed response and identify the wearer as both source and destination; these garment observations cannot transfer or remove possessions. A missing appearance profile can be initialized without inventing appearance details. Malformed existing profiles still require review. Repeated observations preserve existing worn coverage. Later changes in the response take precedence; recognizing their semantics remains a model responsibility.

An existing object's directly established current body placement uses
`observed_placement`. Literary narration can establish this fact without a new
placement verb, such as a sealed sensor remaining secured in a character's assigned
body slot. This basis requires an existing canonical ID, `worn`, an explicit
`attachment_slot`, and no garment displacement. It cannot create items or turn
generic holding, requests, claims, recollections or hypotheticals into placement.

Same-owner observations retain the existing attachment eligibility and body checks.
Repairing stale custody between present participants is narrower: the canonical
object must have `DEFAULT` or legacy empty type, no garment or wearable slots, and
no nonzero known inventory stat/resource effects. This preserves the item's ID,
intrinsic metadata and original acquisition provenance. It does not invent a
handover, execute gameplay callbacks, or classify arbitrary script dependencies
from item prose. Existing rule rejections and unavailable sources remain decisive.

Mixed completed-action and current-placement chains retain exact source order and
continuous custody. Later completed removal or transfer wins. An already resolved
transfer prefix is not replayed merely to recover its final missing binding.
Valid earlier placement evidence remains unchanged; missing, edited or foreign
source evidence can be replaced by the current exact observation. Verification is
bounded to the candidate placements and adds no model request. Existing reviewed
history recovery keeps its same-owner action contract.

Debug's **Restore clothing from history…** analyzes at most 80 recent user/assistant messages (48,000 characters), in chronological order. It proposes only missing garments still owned by the selected NPC, with exact assistant-message citations. The preview displays worn/carried status, descriptions, source quotes, rejected entries and any history limit. It never applies automatically. **Apply reviewed clothing** checks the preview token, evidence and state/history fingerprint again. Any intervening story/state change requires a new preview. It preserves unrelated inventory and does not replace an entire outfit. This is model-assisted recovery, so the owner must review later removals and transfers before applying. It does not infer unmentioned clothing or restore items from excluded older history.

Recovery uses its own history-specific prompt and accepts up to 16 entries. Its wire schema separates existing-item IDs from new-garment descriptions; supplying both identities is invalid. One shared retry covers schema errors or rejected evidence, within the selected role's overall deadline. Evidence repair preserves previously validated proposals; a malformed correction or a correction that drops them leaves the original proposal inspectable. The debug Clothing window offers Main (Complex, default) or Small; existing provider fallback rules still apply.

The initial model payload is capped at 64,000 characters. It includes a compact item-name catalogue, ownership, valid reusable garment metadata and current worn IDs, without duplicate inventories or image-generation metadata. If necessary, the oldest complete messages are excluded; narration and evidence quotes are never sliced. The preview marks excluded history, while apply still checks the original full state/history fingerprint. An irreducible catalogue or a budget with no room for a complete recent message fails before model invocation. Failed previews distinguish prepared context from a successful model review.

Debug → NPC → **Clothing → Recovery requirements** displays the saved session's clothing-layer setting and the NPC's recorded age. An explicit edit updates this session's manifest setting and NPC card, leaves the adventure template and mature-content settings unchanged, and invalidates the previous recovery preview. Unknown age stays unknown until entered by the user. Stale edits are rejected. Settings/age skips name the actual unmet requirements, and identical skip messages are shown once.

Settings/age rejections appear as **Skipped** and do not block other validated garments. Source, evidence, ownership and malformed-state errors block their own candidates. The user selects validated garments; other rejected candidates do not block that selection. Apply revalidates only the selected entries against the same source/state fingerprint. Stable original proposal indices preserve item IDs when applying a subset. Recovery additionally corrects a false underwear flag for unambiguous English/Russian inner-garment names. This is a bounded vocabulary check, not a universal language classifier; body coverage or layer alone cannot distinguish underwear from ordinary skirts, trousers or swimwear. The explicit true flag is never cleared.

The debug inspector's **Scene JSON** button reads persisted evidence without invoking a model or rebuilding anything. It separates the current location/staging/placed items from a selected narrator message's frozen illustration snapshot. The latest 100 narrator messages are selectable. Snapshot status compares the same source hash used by illustration rendering; a match is not a semantic accuracy guarantee. Missing snapshots may never have been captured or may have expired. Current staging is separately marked disabled, not recorded, stale, ready or unconfirmed. Staging defaults to disabled in narration settings.

Cached visual plans/audits are shown only for the selected message, with no current-preset revalidation. Plans are created on demand, bounded by the existing cache, and not used by every illustration route. JSON can be copied or downloaded, including on HTTP installations where the clipboard is unavailable. Access requires session ownership and debug mode; the endpoint never changes state.

Garments that exist only in narration are represented as `new_item` with a null `item_id`; the engine assigns an ID after evidence validation. Recovery's new-item schema requires clothing metadata and wearable slots and cannot accept ordinary items. For each request, the existing-item branch is restricted to the target NPC's actual owned garment IDs. With no eligible recorded garments, that branch is absent. Unknown IDs and existing records with missing/invalid clothing metadata have distinct named errors. Legacy unstructured records are not silently duplicated or assigned invented metadata.

Recovery displays rejected quotes, proposed action basis/disposition, covered/exposed regions and the cited original assistant message. Quotes still require exact contiguous matching; the repair does not normalize or invent evidence. A limited English/Russian underwear-mention check supplements the LLM: detected mentions appear as proposed, explained by a model omission with an exact source quote, or unreviewed. These keyword hints do not establish ownership and never create garments. They cover only messages in the existing recovery window, not all historical prose or every possible paraphrase. Unreviewed mentions remain visible even when other validated garments are selected for restoration.

When the model's single retry still fails, **Correct this proposal** lets the session owner choose worn (including lowered clothing) or fully removed but still owned, copy an exact item quote, and correct exposed regions with an exact placement quote from the same cited message. **Validate correction** updates only the preview and resets its selection token; it makes no model request. Source IDs, ownership, identity and garment metadata remain fixed. Validation rechecks the state/history fingerprint, exact evidence, coverage and clothing/age requirements and preserves other validated candidates. The owner then explicitly selects and restores the corrected garment. Clothing lowered to the knees remains worn with the relevant region uncovered; it is not automatically transferred to the player.

Corrections display separate errors for the item quote, placement quote and exposed regions.
Invalid regions proposed by the model remain visible until explicitly unchecked or reset.
Select text inside the cited original message to populate either quote without retyping;
selection outside that message is ignored. A single exact quote may fill both fields.
Case/whitespace-only suggestions offer an unchanged excerpt from the cited source for
explicit selection, only when the match is unique; paraphrases and combined fragments
are never accepted as evidence. Quote-boundary whitespace is trimmed consistently before
preview and apply, as for live item actions; interior whitespace, case and punctuation
still require exact matching. Length limits use Unicode characters on both client and server.

### Equipment card projection

NPC cards read canonical ownership and `visual_profile.worn`; they never maintain a
second equipment inventory or issue actions. RP continues to update those records
through the existing wardrobe and shared post-narration reconciliation passes.
Visible garments use canonical `wearable_slots` (alternatives, not duplicate
placements), falling back to garment coverage. Layers share one slot. Slot hover,
keyboard focus or tap opens a viewport-constrained list inside the native dialog.

Optional `visual_profile.body` records `form` (`humanoid`, `non_humanoid`, `unknown`)
and an optional `silhouette` (`male`, `female`, `neutral`). An explicit body shape
wins over NPC type; otherwise HUMANOID uses the silhouette, ANIMAL uses a list and
unclassified types use a list. Gender chooses only the silhouette, never anatomy.
Legacy player equipment keeps its existing mechanical actions and humanoid layout
unless an explicit body form specifies otherwise.

A worn ordinary object can have `attachment_slot` (`vaginal`, `anal`, `uterine` or
`penile`) without becoming clothing or covering other garments. The optional
`body.attachment_slots` means unassessed when null and explicitly unavailable when
empty. Completed, evidence-backed placement requires an established adult and
cannot override an explicit exclusion. Carrying, holding or transferring removes
the old binding. Each display group remains one position: clitoris/labia/vagina,
sphincter/anus, uterus, and penis/testicles. No extra model call is added.

For a physically present, visible character with a valid profile, known adult age
and detailed clothing enabled, the read-only card adds `clothing.placement_status`
(`available`, `unavailable` or `unassessed`) and `placement_slots`. Each exposed key
has `empty`, `occupied` or `unconfirmed` status. Declared regions stay visible when
empty. An owned binding with missing or invalid proof is unconfirmed and does not
reveal its item's name or ID. Confirmed items require an unchanged exact quote,
hash and any saved span in a non-debug assistant/user message from the same session
with the matching source role. Explicit exclusions remain authoritative.

Known bodily conditions retain their canonical IDs, parts and saved state.
Exact known part identifiers and explicit aliases add `display_slots` for hover
grouping; unknown parts stay in the general condition list. Ordinary body positions
do not require adult age or detailed clothing. The four additional groups follow
the same metadata gates above. When availability is unassessed, a currently
source-verified public condition or confirmed occupied binding may establish its
reported group without asserting a complete body layout. Narrated condition proof
must match the original non-debug assistant message in the same session; explicit
public manual corrections are also eligible. An adult owner view with detailed
tracking and mature content enabled can also show private conditions already
disclosed in an unchanged, non-debug assistant message from that session. The card
labels these **Known from narration**. This read-only view does not make them public
or change NPC, memory, image or shared-knowledge projections. Private manual facts,
unavailable sources and resolved conditions do not establish new groups. A status-only group has no item row, and
its empty placement status makes no claim that the body is healthy or clean.

With **Show empty slots**, an unassessed humanoid layout can show additional
presentation markers labelled **Not assessed**. The silhouette chooses their
positions, never canonical anatomy or availability. Explicit exclusions stay
authoritative; no inventory, body declaration or condition is created by the view.

Partial clothing displacement remains worn and owned. A source-confirmed displaced
garment remains known on the card even if it no longer covers its original region.
Its optional wear `source` records the exact quote/span, narration hash and saved
assistant message ID. The completion hook binds newly applied placements after the
assistant is saved; wardrobe recovery binds its already-saved source directly.
Missing, edited or foreign-session sources cannot reveal otherwise hidden items.
Copy/import remaps proof IDs to local history; checkpoint/replay restores the same
canonical profile. Source proof is omitted from compact model context, while current
placement facts remain available. Underwear age/detail and scene-presence rules still
apply. These additive fields preserve version 1 profiles and their legacy shape.
