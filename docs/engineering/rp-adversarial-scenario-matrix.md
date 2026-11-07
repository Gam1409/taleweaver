# RP engine scenario matrix

This is an engineering backlog and evaluation design, not a claim that every row already passes. It covers ordinary play as well as attempts to confuse identity, time, ownership, knowledge and causality. Existing automated tests establish specific host contracts; mocked responses do not establish live-model comprehension.

**Covered boundary** means a named test family exercises the relevant host boundary. **Probe** means the combined scenario still needs a dedicated regression or live evaluation. **Gap** means a limitation is confirmed in the current implementation. Never report a probe as a discovered defect without reproducing it.

## Confirmed gaps worth addressing first

| Priority | Gap | Why it matters | Proposed next change |
| --- | --- | --- | --- |
| P1 | Exact quote validation does not prove semantic interpretation. | The model can cite a real sentence but attach it to the wrong subject, actuality or operation. | Evaluate attribution and completed-action errors separately; keep host IDs, permissions and supported operation checks. |
| P1 | Long-session memory has several independent finite archives. | RAG summaries do not remove CHPM's 8,192-event limit or Living World's 512-event limit and timeline-wide deliberation cap. | Separate exact audit storage from bounded working views; preserve source/replay contracts rather than increasing caps. |
| P1, addressed for new replies | Legacy character journal recording timestamps are not game-clock timestamps. | Background learning can finish many turns after the source event. Dating it with the worker's current clock would be wrong. | New replies now preserve source game minutes through learning and summaries. Older unknown game dates remain unknown. |
| P2 | Several journal paths expand the complete compressed archive. | A bounded prompt alone does not bound CPU, allocation or JSON rewrite cost. | Measure 20/200/2,000-turn cases; design an invalidatable working projection and cold archive access. |
| P2 | Physical conditions have no configured elapsed-time evolution. | Waiting does not automatically dry a surface, expire a timed effect or heal a wound. | Add only explicit adventure-supported transition rules with game-clock tests; no universal medical assumptions. |
| P2 | Physical conditions attach to known actors/items, not rooms or newly created same-pass item IDs. | A flooded laboratory, contaminated floor or newly materialized dirty coat cannot all be represented by this first ledger. | Define scene effects and two-phase canonical item binding separately. |
| P2 | Public character summaries and private NPC memory have different audiences. | Automatically feeding public history into an NPC's mind could give it knowledge it never acquired. | Preserve observer scope and epistemic provenance during any consolidation. |
| P3 | Calendar months are not fixed-duration time-passage units. | “One month” cannot universally mean 30 days. | Support an explicit calendar anchor/policy before converting months; existing day/week passages remain precise. |

Implementation references: [physical state](../persistent-physical-state.md), [time passages](../vn-time-passages.md), [memory assessment](npc-memory-consolidation.md), [NPC Personality capacity](../../backend/engine/chpm/capacity.py), [journal records](../../backend/engine/npc_journal/records.py), [Living World contracts](../../backend/engine/living_world/schema.py).

## A. Time and long sessions

| ID | Player situation | Expected invariant | Coverage / next check |
| --- | --- | --- | --- |
| A01 | Wait ten minutes without changing rooms; repeat several times. | The saved game clock advances by the accepted durations; lack of physical changes does not freeze it. | Covered boundary: `test_vn_time.py`, `test_condition_clock_turn.py`. |
| A02 | “Three days passed.” | Convert to exactly 4,320 minutes once; narrate and save the same target. | Covered boundary: `test_vn_time_passage.py`; live phrasing probe. |
| A03 | Remain in an isolated shelter for 30, 90 or 180 days. | Preserve the long story clock and due events; process background work within declared budgets. | Covered boundary: `test_vn_time_passage_world.py`, native and Concordia with local model responses. Recurring schedules remain a separate capacity probe. |
| A04 | “In three days we will meet”; “last year I waited three days.” | Neither a future appointment nor a recalled interval advances the present. | Covered classification contract: `test_vn_time_passage.py`; actual classification is a live probe. |
| A05 | Promise to meet tomorrow, then wait until the next day. | The appointment becomes relevant, but the promise is not automatically considered fulfilled. | Probe: time, agenda and narrative consequence integration. |
| A06 | Wait a week in a world using custom ritual-count units. | Do not silently convert days to arbitrary units. | Covered boundary: `test_vn_time_passage.py`; an explicit author mapping is a future feature. |
| A07 | Regenerate the reply after a long wait, then reload or copy the save. | Replay replaces that turn's elapsed time; copying preserves the accepted clock. | Covered replay/condition boundaries; dedicated long-skip copy combination is a probe. |
| A08 | A portal sends the hero to an earlier date. | Do not subtract game time as an ordinary elapsed duration; define a branch or explicit world rule. | Probe / design requirement: time travel is not a normal wait. |
| A09 | The device clock jumps, a browser tab crashes, or two tabs reconnect. | Real-world absence is accounted once; UTC regression never adds fictional time twice. | Covered boundary: `test_living_world.py`. |
| A10 | Two unrelated events have the same timestamp. | Preserve stable causal/source order; never use arbitrary name order to claim one caused the other. | Probe across public journal, RAG and private evidence; CHPM host order has its own contract. |

## B. Identity, evidence and knowledge

| ID | Player situation | Expected invariant | Coverage / next check |
| --- | --- | --- | --- |
| B01 | Address “Doctor Rin Aoyama” as “Rin” halfway through a scene. | Resolve an established unambiguous alias to the same canonical NPC. | Probe with narration labels, portrait lookup and journal extraction together. |
| B02 | Two guards both introduce themselves as Alex. | Keep separate IDs; a shared name alone cannot merge them. | Probe: identity ambiguity and speaker attribution. |
| B03 | An impostor claims another NPC's name. | Save the claimed identity as a claim; do not transfer inventory, personality or memories. | Probe: identity versus self-introduction. |
| B04 | Tell a lie to one NPC, whisper the truth to another. | Different observers retain different evidence; narrator knowledge is not universal knowledge. | Probe: audibility and private observer recall. |
| B05 | Forge a letter saying a king died. | Reading the letter establishes its contents, not the king's death. | Probe: document attribution through summaries and RAG. |
| B06 | Say “I take her key” while she blocks the attempt. | A request/attempt does not become a completed transfer. | Covered evidence/ownership boundaries; adversarial narration probe. |
| B07 | Quote an old conversation word-for-word in a new room. | Retrieval distinguishes the retelling from the original event and its time. | Probe: near-identical vectors and episode anchors. |
| B08 | Mention an absent person in a dream or hypothetical. | Do not create or move that person into the current scene. | Probe: introduction, presence and actuality together. |
| B09 | Erase or edit the message that established a memory. | Invalidate derived sources and summaries; stale vector text cannot restore the old fact. | Covered boundary: memory source/retraction tests; combined private/public probe. |
| B10 | Import another adventure containing the same actor and scene IDs. | Owner, session, branch and observer filters prevent cross-save recall. | Covered ownership boundaries; deliberately colliding-ID fixture is a probe. |

## C. Motives, commitments and personality

| ID | Player situation | Expected invariant | Coverage / next check |
| --- | --- | --- | --- |
| C01 | Distract an NPC for twenty exchanges after a clear promise. | The open commitment remains available even if recent dialogue changes topic. | Probe with zero transcript window and several competing commitments. |
| C02 | Ask a proud character to betray a central value for convenience. | Its actual values, goals and evidence drive the decision; player preference is not authority. | Live psychological evaluation required. |
| C03 | Reward a reluctant NPC once, then demand an immediate personality reversal. | A single reward cannot silently replace original identity. | Probe: short versus repeated developmental evidence. |
| C04 | Repeatedly help an initially suspicious character. | Gradual change may occur when supported, without erasing caution or inventing certainty. | Live trajectory evaluation, not prose-style scoring. |
| C05 | An NPC verbally agrees while secretly intending to leave. | Speech, belief, intention and completed action remain distinct. | Probe: deceptive action candidates and evidence traces. |
| C06 | Two legitimate personal goals conflict. | Record the selected motive and leave the unfulfilled goal open unless explicitly abandoned. | Probe: agenda closure and candidate selection. |
| C07 | An NPC's promised task becomes impossible because an object is destroyed. | The obstacle persists; the goal is reconsidered rather than marked completed. | Probe: causal graph, item state and agenda linkage. |
| C08 | An adult NPC has an authored intimate preference, or lacks it, under the same social pressure. | Behavior follows that specific character's traits and boundaries; preference is not inferred from pressure alone. | Live paired-persona evaluation; no universal automatic trait update. |
| C09 | Edit the character card after its psyche was initialized. | Explain pinned identity behavior; do not silently reset private history. | Covered policy in CHPM documentation; explicit migration remains separate. |
| C10 | A frightening event affects behavior for many later scenes. | Preserve the event and supported effects without inventing a clinical diagnosis or permanent new personality. | Probe: experience/development versus canonical physical state. |

## D. Locations, groups and background actions

| ID | Player situation | Expected invariant | Coverage / next check |
| --- | --- | --- | --- |
| D01 | “Let's go to the lab” when “Clinical Research Laboratory” already exists. | Resolve the existing logical destination when unambiguous; do not duplicate it from a shortened label. | Probe: location resolution plus group transition. |
| D02 | Two plausible laboratories exist. | Clarify in-world or retain uncertainty; do not teleport to an arbitrary match. | Probe: ambiguity handling. |
| D03 | Lead three NPCs through a doorway; one refuses or is immobilized. | Move the hero and confirmed followers together; keep the refusing/blocked NPC in place. | Probe: atomic group transition and independent agency. |
| D04 | “The laboratory is empty” while an NPC is canonically inside. | Resolve the contradiction; prose cannot silently hide a present person. | Probe: narration against authoritative presence. |
| D05 | Move through a locked exit, or use a portal with a rule exception. | Enforce normal gates; accept only an explicitly supported exceptional transition. | Covered guard boundaries; portal exception combination is a probe. |
| D06 | A background NPC tries to walk away during a direct conversation. | Defer permitted background movement near the active interaction, without blocking foreground choices indefinitely. | Existing Living World interaction boundary; starvation/long-scene probe. |
| D07 | Address all twenty people in a room. | Keep the full cast present; honor explicit active-agent limits rather than silently dropping addressees. | Probe: group overflow, user messaging and fallback policy. |
| D08 | NPCs follow hourly schedules during a three-month skip. | Report actual backlog and budgets; do not claim an unprocessed quarter-year was simulated. | Gap: finite recurring journal/call budgets; requires an archival/scheduling policy. |
| D09 | Split the party, then reunite it after independent events. | Preserve separate locations, knowledge and state; share only what reunion actually communicates. | Probe: multi-scene causal continuity. |
| D10 | A vehicle carries the group while characters move inside it. | Distinguish relative presence from world location; do not create multiple unrelated moving rooms. | Probe / potential world-model extension. |

## E. Objects, transactions and references

| ID | Player situation | Expected invariant | Coverage / next check |
| --- | --- | --- | --- |
| E01 | Receive a newly described ordinary item. | Assign one canonical ID, validate evidence and record its actual owner. | Covered narrated-item boundary; model completeness still needs live evaluation. |
| E02 | Hand over an object that was only lowered or moved aside. | Clothing placement or an attempted action is not proof of transfer. | Covered wardrobe/recovery boundaries; joint narrative probe. |
| E03 | Two identical black keys have different owners. | Resolve the selected canonical object; do not merge by description. | Probe: ambiguous references and ownership. |
| E04 | Put a unique object in a bag, give away the bag, then open it. | Nested ownership, access and container contents remain coherent. | Probe: nested container semantics. |
| E05 | Steal an item secretly, then accuse its previous owner of losing it. | Physical possession and each person's belief can diverge. | Probe: ownership versus knowledge propagation. |
| E06 | Sell, lend, rent or pawn the same item. | Distinguish possession, return obligation and any modeled legal ownership. | Probe / contract modeling requirement; do not infer support from simple transfer. |
| E07 | Break, repair or consume part of an object. | Preserve identity and explicit state/quantity; do not duplicate a consumed item through recall. | Probe: partial quantity and durability semantics. |
| E08 | Create a dirty garment and describe its stain in the same reply. | Resolve the new canonical item before binding its condition. | Confirmed gap in the first physical-condition pass. |
| E09 | An image or description repair fails. | Keep valid item identity/state and the established placeholder; no replacement object is granted. | Probe: repair failure and inventory stability. |
| E10 | A local phrase means either a person's hand or a door handle. | Use scene/action context; uncertainty must not choose an unrelated target with side effects. | Live ambiguity probe in Russian and other languages. |

## F. Clothing, appearance and visibility

| ID | Player situation | Expected invariant | Coverage / next check |
| --- | --- | --- | --- |
| F01 | A red undergarment is covered by opaque jeans and a sweater. | Another NPC cannot inspect the hidden garment from canonical ownership alone. | Probe: complete visibility pipeline and narration. |
| F02 | The sweater becomes transparent while the jeans remain opaque. | Reveal only the actually visible upper garment/region. | Probe: partial visibility with layered clothing. |
| F03 | Lower a garment to the knees without removing it. | Keep ownership and worn/partial placement consistent; expose only supported regions. | Covered wardrobe correction boundary; live extraction probe. |
| F04 | Remove a coat and carry it, place it on a chair, then give it away. | Keep separate worn, carried, loose and transferred states of one ID. | Probe across four consecutive transitions and reload. |
| F05 | Hide an object under clothing, then change outfits elsewhere. | Hidden inventory does not automatically become public or vanish. | Probe: possession, placement and observer knowledge. |
| F06 | Wear two visually similar garments on different layers. | Preserve both IDs, layer ordering and explicit region coverage. | Probe: duplicate-looking layers. |
| F07 | Recover old clothing after a later valid transfer. | Latest established ownership wins; recovery cannot resurrect the older owner's possession. | Covered recovery source boundary; long-history live probe. |
| F08 | Tear or stain clothing without changing the garment itself. | Keep intrinsic description separate from current condition. | Covered design boundary; visual generation/state synchronization is a probe. |
| F09 | Change outfits off-screen, then return to an NPC who saw the old outfit. | Canonical appearance updates; the other NPC may notice a change without learning hidden details. | Probe: time, visibility and memory interaction. |
| F10 | A generated portrait still depicts a previously removed coat. | Stale imagery cannot overwrite canonical clothing or establish an observed fact. | Probe: asset provenance and stale generation results. |

## G. Bodies, surfaces and consequences

| ID | Player situation | Expected invariant | Coverage / next check |
| --- | --- | --- | --- |
| G01 | Injure the neck, change rooms, and omit the wound for fifteen replies. | The wound stays recorded and available to the appropriate observer. | Covered physical-state/CHPM boundary; live long-story probe. |
| G02 | Disinfect or stitch that wound. | Treatment does not establish full healing. | Covered physical condition transition tests. |
| G03 | Clean one hand while the other remains dirty. | Resolve only the supported subject/part; a broad ambiguous record needs explicit correction. | Probe: condition granularity and partial operations. |
| G04 | Wipe an external fluid trace while another condition is internal or elsewhere. | Do not clear every fluid condition on the actor. | Covered subject/part boundary; live attribution probe. |
| G05 | An adult intimate event leaves a persistent bodily condition, followed by travel and conversation. | Preserve explicitly established state until an evidenced change; no automatic health or reproductive inference. | Probe: extraction, privacy and delayed consequences. |
| G06 | Wait several days after a wound or wet surface was recorded. | Current implementation keeps it until an explicit update; do not claim realistic decay already exists. | Gap: adventure-defined timed transitions. |
| G07 | Wash a borrowed coat and return it to its owner. | The condition follows that item ID; cleaning does not affect the owner's other coat. | Probe: item identity across ownership and condition changes. |
| G08 | Set fire to a room or flood a laboratory. | Model environmental state separately from a character's dirt or pain. | Gap: scene-level condition representation. |
| G09 | Use healing magic, regeneration or a prosthesis. | Apply explicit world rules to named conditions, without resetting all historical or psychological effects. | Probe: rule-governed exceptional recovery. |
| G10 | The model proposes zero changes after an important event. | Show an empty extraction distinctly from verified absence; keep previous facts. | Covered diagnostics and browser/SSR boundaries. |

## H. Genre, causality and technical recovery

| ID | Player situation | Expected invariant | Coverage / next check |
| --- | --- | --- | --- |
| H01 | Move a diplomatic gift; a messenger reports it; a king interprets it as an insult. | Preserve separate physical action, communication and interpretation links; do not make war automatic. | Probe: long causal chain with scoped knowledge. |
| H02 | Poison food, swap the plates, then conceal the container. | Track object identities, exposure and evidence; suspicion does not prove poisoning. | Probe / domain-rule requirement for delayed effects. |
| H03 | A magical disguise, illusion or hologram changes perceived appearance. | Separate actual state from each observer's supported perception. | Probe / perception-rule extension. |
| H04 | Clone a person or copy an artificial intelligence. | Create distinct identities with an explicit memory-copy rule; shared appearance is not one NPC. | Probe: identity and branch semantics. |
| H05 | Send a delayed message, cancel it, or intercept it. | Knowledge changes only after modeled delivery; cancellation remains evidenced. | Probe / scheduled communication extension. |
| H06 | Produce malformed JSON for items, time, conditions or an optional lookup. | Invalid optional candidates cannot erase valid independent facts; protect canonical state and expose diagnostics. | Covered individual schema/failure boundaries; combined stress probe. |
| H07 | Disconnect after text starts, time out inference, then press retry/regenerate. | Recover from saved turn state; avoid lost replies, duplicate actions or extra elapsed time. | Existing recoverable-turn tests; browser/network fault-injection probe. |
| H08 | Toggle debug, edit an NPC or move the player while a model request is in flight. | Mutation fencing rejects stale results; UI remains usable and canonical updates are not overwritten. | Probe across debug, regeneration and session lease. |
| H09 | Repeatedly retrieve the same incident through a summary, quote and vector hit. | Treat them as one evidence lineage; repetition cannot amplify belief as independent confirmation. | Probe: duplicate provenance through recall and cognition. |
| H10 | Run 2,000 turns with similar events, twenty NPCs and intermittent model failures. | Measure memory relevance, fixed prompt budgets, archive cost, capacity warnings and recovery; no silent personality reset or discarded history. | Long-run benchmark backlog; not established by short mocked tests. |

## Turning this matrix into tests

Prioritize host integrity first: clock, identity, ownership, visibility, source invalidation, replay and independent failure paths. Test the same incident in nearby and distant scenes with deliberately similar wording. For retrieval, score whether the correct episode and unresolved goal were returned, not whether the model wrote attractive prose.

Next run paired personality trajectories under identical events, including misleading player pressure, omitted reminders and conflicting goals. Record selected action, motive trace, source coverage and justified changes to beliefs/agenda. Stylistic variety is a separate measurement.

Live runs should use a small fixed seed set, then expand to dense turns and long campaigns. Preserve raw source fixtures and expected invariants so changing a prompt cannot quietly move the acceptance criteria. Report mock host results separately from live semantic/psychological results and actual latency.
