# Situation, personality and emotion: research and implementation plan

Status: research draft, 2026-11-10. No runtime or prompt changes are included.

The owner's 25% character / 75% situation example expresses a product goal:
intense events should substantially affect an NPC's current response without
making the cast interchangeable. It is not a measured psychological ratio and
must not become a numeric mixing rule in code.

## Reading scope and evidence

This is a review of accessible textbook sections, one publisher-provided handbook
chapter, selected passages of the supplied Freud book, primary-research abstracts
and relevant parts of a full LLM context paper. It is **not** a claim that several
complete textbooks or the entire Freud book have been read. Remaining full-book
reading and synthesis must be tracked explicitly before calling that work complete.

| Source | Material reviewed | Contribution and limits |
| --- | --- | --- |
| Spielman, Jenkins & Lovett, *Psychology 2e*, [10.4 Emotion](https://openstax.org/books/psychology-2e/pages/10-4-emotion) | Complete section | Distinguishes experience, appraisal, physiology and expression; surveys competing emotion theories. A survey is not proof that any one account is universally correct. |
| Same textbook, [11.4 Learning Approaches](https://openstax.org/books/psychology-2e/pages/11-4-learning-approaches) | Complete section | Person, behavior and environment interact; situational interpretation and perceived ability matter. |
| Same textbook, [11.7 Trait Theorists](https://openstax.org/books/psychology-2e/pages/11-7-trait-theorists) | Complete section | Traits describe tendencies and distributions, not mandatory behavior in every scene. |
| Same textbook, [14.1 What Is Stress?](https://openstax.org/books/psychology-2e/pages/14-1-what-is-stress) and [14.4 Regulation of Stress](https://openstax.org/books/psychology-2e/pages/14-4-regulation-of-stress) | Complete sections | Threat/challenge appraisal, perceived coping resources, control and social support influence reactions. Do not turn introductory physiological models into fixed RP timers. |
| Evans & Crum, “Mindset Regulation,” in Gross & Ford, eds., *Handbook of Emotion Regulation*, 3rd ed. (2024), [publisher excerpt](https://www.guilford.com/excerpts/gross_ch10.pdf?t=1) | Chapter main text, pp. 87–91; not the whole handbook | Existing beliefs can affect appraisal, attention and regulation. This chapter does not establish a universal character/emotion formula. |
| Freud, *Three Essays on the Theory of Sexuality*, supplied Russian edition titled [*Psychology of Sexuality*](https://cpp-p.ru/wp-content/uploads/2015/05/Freyd_Zigmund__Psihologiya_seksualnosti.pdf) | Prefaces and selected passages on excitation, tension, inhibition, disposition and experience; 74-page PDF, not yet read in full | Historical perspective on conflicting tendencies and inhibition. Do not equate Freudian repression with experimentally studied expressive suppression or adopt historical diagnostic/gender claims as engine rules. |
| Mischel & Shoda (1995), [cognitive-affective personality system](https://doi.org/10.1037/0033-295X.102.2.246) | Primary abstract through Europe PMC | Situation-specific patterns can be consistent expressions of the same person. Full text was not reviewed. |
| Fleeson (2001), [traits as distributions of states](https://doi.org/10.1037/0022-3514.80.6.1011) | Primary abstract through Europe PMC | Three experience-sampling studies report substantial within-person variability alongside stable individual differences. Does not establish RP weights. |
| Gross (2002), [emotion regulation consequences](https://doi.org/10.1017/S0048577201393198), and Gross (2013), [taking stock](https://doi.org/10.1037/a0032135) | Primary abstracts through Europe PMC | Feeling and its outward suppression are distinct; regulation strategies have different consequences. Full texts were not reviewed. |
| Scherer (2009), [emergent emotion processes](https://doi.org/10.1098/rstb.2009.0141) | Abstract and publisher metadata; full-text retrieval unsuccessful | Relevant theoretical model for virtual agents, not an implemented or validated model in TaleWeaver. |
| Toates (2009), [sexual motivation, arousal and behavior](https://doi.org/10.1080/00224490902747768); Chivers et al. (2010), [subjective/physiological agreement meta-analysis](https://doi.org/10.1007/s10508-009-9556-9); Basson (2000), [responsive desire model](https://doi.org/10.1080/009262300278641) | Primary abstracts through Europe PMC | Distinguish motivation, bodily response and reported experience; avoid a mandatory linear progression. The meta-analysis reports population findings, not NPC-specific probabilities. |
| Bonanno (2004), [loss, trauma and resilience](https://doi.org/10.1037/0003-066X.59.1.20) | Primary abstract through Europe PMC | Loss does not impose one universal outward response or recovery trajectory. |
| Liu et al. (2024), [*Lost in the Middle*](https://aclanthology.org/2024.tacl-1.9/) | Main findings, methods and relevant discussion from the full paper | Context length and information placement affect use of evidence. These are older models and retrieval tasks; the paper does not benchmark Artemis RP or guarantee a prompt-layout fix. |

No book text is to be copied into production prompts, training data or a new
runtime library. The implementation should express small original engineering
contracts, with research references kept in documentation.

## Working synthesis

An NPC's profession is a role, not a complete personality. Baseline temperament,
values, goals, relationships, learned expectations and current state are related
but distinct. A composed person can experience intense fear, grief or excitement;
the same person can express those experiences differently in different situations.

Use the following as an engineering decomposition, not a claim that the brain
performs serial LLM-style steps:

1. **Perceived situation:** what is happening, who is involved, what changed, what
   remains ongoing, and what this observer can actually know.
2. **Personal significance:** threatened or supported goals, expectations,
   relationships, bodily conditions, uncertainty, control and available help.
3. **Current experience:** potentially mixed feelings and activation, with causes,
   intensity, duration/freshness and uncertainty.
4. **Regulation and intention:** what the person tries to do or conceal while
   experiencing that state. Feeling, action tendency and chosen action can differ.
5. **Expression:** speech, rhythm, pauses, attention, movement and fictional
   internal thought. Quiet expression does not establish absent feeling.
6. **Feedback:** the actual response and outcome may change the situation and the
   next appraisal; a successful check is not an automatic psychological resolution.

These components can interact and recur. The same outward response can result from
different experiences, and similar bodily activation can have different meanings.
Do not force crying, panic, desire or loss of control from an event label alone.
Neither “professional” nor “intense emotion” should be an unconditional veto.

Grief can include distress, numbness, practical activity and moments of relief.
Fear can coexist with effective action. Excitement can coexist with uncertainty.
Attempts to remain composed can succeed, partly succeed or fail. None of these
patterns requires rewriting the original character card after one turn.

## Existing implementation and the demonstrated gap

The relevant owners already exist:

| Responsibility | Existing owner |
| --- | --- |
| Ongoing scene processes/effects, final observed actions and exact sources | `backend/engine/scene_continuity/` |
| Message-time public cast and visual facts | `backend/engine/scene_illustrations/snapshots.py` |
| Body/garment conditions | `backend/engine/physical_conditions/` and clothing owners |
| NPC-scoped knowledge and source reconciliation | CHPM perception, host adapter, host sources and appraisal context |
| Temporary mixed experience and game-time freshness | CHPM `experience.py` and core experience reducer |
| Source-grounded goals, choices and recalled episodes | CHPM motivation, agenda, causal memory and semantic recall |
| Narration, factual review and portrait presentation | Existing narrator contract, review and presentation owners |

The ordinary VN social planner receives up to 4,000 characters of the last scene.
CHPM replaces that planning path for its controlled actors. Its current perception
classifies the new player message; it does not independently classify the full
preceding scene. Its scene projection includes persistent scene records, while
final-frame actions are currently consumed by visual presentation instead.

Consequently, a turn can have verified frame actions and substantial narrated
context but few useful situation facts in the NPC's decision input. A detailed
identity and its professional goals then dominate the available evidence. Adding
more instructions to “be emotional” cannot recover context that was not supplied.

Other existing boundaries also matter:

- Experience appraisal requires a current observed trigger. Recalled events alone
  cannot repeatedly refresh or intensify an experience.
- Appraisal evidence currently excludes host frames; authoritative scene/body
  context and citable affect triggers therefore need an explicit integration audit.
- Motive grounding includes authored/declared personal stakes. This should not be
  interpreted as requiring a character-card statement permitting each feeling.
- Repeated roots are not independent confirmation. Preserve this protection.
- Rejected actors use the owner-selected inactive policy: no new decisions or
  dialogue. Do not loosen this merely to make every scene appear more expressive.
- Semantically similar episodes remain historical sources with separate actors,
  locations and times. Similarity is not proof that an earlier scene is occurring now.

The observed narrator outputs were preserved by review. That finding establishes
absence of post-generation text clipping in those samples, not absence of
generation-time constraint effects or a universal quality result.

## Proposed implementation sequence

### 0. Finish the research contract and freeze a baseline

- Finish relevant reading of the supplied book and track unreviewed material;
  compare historical ideas with modern evidence before adopting any claim.
- Keep the current “situation missing → role stereotype” reproduction.
- Define success as context-sensitive, recognizable characterization, not a
  fixed number of emotional words or a required emotion per event.
- Prepare matched on/off comparisons from the same before-turn snapshot, history,
  input and effective model/sampling settings. Existing uploaded examples have
  different inputs/history and are diagnostic examples, not a controlled A/B test.

### 1. Repair the existing scene-to-observer handoff

- Project a bounded view from the current scene owner and the latest completed,
  source-checked moment. Audit the frozen public cast for who could observe it.
- Preserve message ID, revision, content hash, exact occurrence/span, scene and
  game time. Do not reconstruct missing history or infer another NPC's secrets.
- Label a last observed action as last observed. It must not become an indefinitely
  ongoing process. Ongoing activities belong to persistent scene records.
- Reject changed, missing, incomplete, old-room and inaccessible sources. Legacy
  saves without sufficient observer proof must not silently become omniscient.
- Supply the same observer-scoped situation to lookup, decision and narration
  review. Reuse the existing request and stores; add no extraction model call.

### 2. Connect situation and current experience

- Reuse existing experience and condition owners. Establish what can ground a
  new appraisal versus merely contextualize a retained one.
- Keep current causes and relevant personal stakes close together in model input.
  Traits affect appraisal/regulation without dictating the feeling.
- Preserve mixed states, unknowns, unresolved causes, game-time freshness and
  later explicit resolution. Silence and unrelated dialogue are not recovery.
- Prefer existing explanation/source fields. Add a persisted field only if the
  reproduction proves that an existing owner cannot represent the required data.
- Do not invent numerical physiology, a universal decay rate, or permanent trait
  changes from a temporary strong state.

### 3. Make relevant memory support the current situation

- Audit the existing query construction and ranking against current participants,
  scene, open causal threads and relevant stakes. Keep existing embedding batches.
- Preserve why an episode is relevant and its original time/place/observer.
- Current canonical outcomes and current observations override remembered details;
  recalled feelings do not prescribe the current feeling or action.
- Test repeated phrasing, quoted recollections, similar events elsewhere and
  retracted sources. Avoid a second memory system or generic “emotional examples”
  that the model could mistake for actual shared history.

### 4. Align generation and verification

- Describe the selected course separately from how it is experienced and expressed.
  A decision to act professionally can coexist with strained speech or tears.
- Keep the original voice recognizable and make relevant situation effects
  available to prose without a compulsory checklist of gestures or interjections.
- Keep factual repair and joint action compatibility. Ordinary emotional delivery
  is not by itself a new world action, decision, promise or contradiction.
- Review the existing contracts as a whole. Remove contradictory requirements
  rather than accumulating additional instruction paragraphs.
- Keep model reasoning private; request compact task outputs and source bindings,
  not a verbose psychological essay or hidden chain of thought.

### 5. Validate behavior and performance

- First verify host plumbing with meaningful regression tests and no live calls.
- Then use matched, repeated model comparisons when a live test is explicitly
  resumed. Log effective inputs, outputs, decisions, sources and validation.
- Measure request count, input/output tokens where supplied, queue time, time to
  first token and complete-turn latency. Do not exchange a context bug for more
  sequential model calls or silently increased budgets.
- Separate schema success, correct source transfer, factual consistency and
  literary/psychological quality. Mocked tests establish only the former boundaries.

## Minimum evaluation matrix

| Pair or sequence | Required distinction |
| --- | --- |
| Same composed NPC: routine exchange / sudden danger | The event affects the response without requiring a new personality. |
| Same danger: trained rescuer / unprepared visitor | Different appraisal/coping and recognizable voices; neither is automatically emotionless. |
| Controlled grief / open grief | Both can be intense; quiet speech is not proof of recovery. |
| Uncertain bad news / confirmed loss / later practical question | Preserve uncertainty, then consequences, through the detour. |
| Relief after danger / threat continuing | Relief requires a relevant change; quiet dialogue alone does not end danger. |
| Current fire / remembered fire in another room | Similar wording must not confuse current and historical events. |
| Same quotation in an event and later recollections | Exact occurrence and source identity remain distinct. |
| Joy / anticipation / disappointment | Positive activation does not force the same expression or choice. |
| Adult attraction with mixed emotions / routine friendliness | No automatic desire, agreement or relationship rewrite from a generic cue. |
| Bodily activation / reported feeling / chosen action | Keep separate; an inference about one is not proof of the others. |
| Ongoing activity / completed activity / remaining effects | Different lifetimes and correct ownership across turns. |
| Nearby witness / absent NPC / later arrival | Preserve privacy and each observer's access. |
| One rejected actor / accepted peer | Localized failure and unchanged factual/psychological boundaries. |
| No significant event / one changed fact | Empty output must not hide a missed meaningful change. |
| Reload, rewind, regeneration and partial history copy | Restore or invalidate the exact sources and game-time state. |
| Long detour and explicit time skip | Distinguish retained concern, unassessed current intensity and actual resolution. |

For model evaluation, rate situational responsiveness, retained identity, causal
continuity, credible expression, factual integrity and observer privacy separately.
Use blinded comparisons where practical and report variation across repeats.
No percentage improvement in “realistic psychology” is justified by a small sample.

## Completion boundary

This document is a concrete research/engineering plan. It does not claim a completed
literature review of whole books, a clinical model, an implemented scene handoff,
or a verified improvement in live RP quality. Runtime work starts only after the
research synthesis and implementation choices are worked through in this order.
