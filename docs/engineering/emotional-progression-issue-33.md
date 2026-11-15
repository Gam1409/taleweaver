# NPC Personality: emotional progression and expression

Working plan for [issue #33](https://github.com/Gam1409/taleweaver/issues/33).
Baseline: main `37c4052f91e54ab16325a2bbc1e4f2fdb20a7a52`, including merged #32.
Status: reading complete; first bounded packing repair and evaluation fixtures
implemented, with focused offline checks passing. Live emotional quality remains
unrated. See the [research synthesis](emotional-progression-research.md)
and [matched-case specification](emotional-progression-cases.md).

## Goal and ownership

Improve believable emotional continuity and expression inside **NPC Personality
(CHPM)**. An NPC should respond to what matters to that character, retain relevant
unresolved circumstances, and express or regulate a feeling in an individual way.
Strong expression and restrained expression must both remain possible.

The existing personality, experience, belief, agenda, causal-memory and notebook
owners remain authoritative. Narration and portrait presentation consume their
bounded outputs; they do not become another psychological controller. Existing
presentation without CHPM remains compatible. Ordinary-mode narration and the
repetition work already delivered in #24 must not acquire a second emotion engine.

This work does not require model training, a particular provider, a clinical
diagnosis system, a complete simulation of physiology or claims about consciousness.

## What already exists

| Responsibility | Existing implementation and boundary |
| --- | --- |
| Authored character | `backend/engine/personality/profile.py`: traits are tendencies, with explicit exceptions under pressure; CHPM identity remains pinned. |
| Perception | `chpm/perception.py`, `host_scene.py`, `host_observations.py`, `observation_sources.py`: observer-scoped speech, current facts and source-checked scene context. |
| Appraisal and motives | `chpm/appraisal.py`, `motivation.py`, `cognition.py`: source-bound interpretations, personal stakes and selected intentions in the existing proposal request. |
| Current experience | `backend/engine/chpm/experience.py`, `backend/engine/chpm/core/experience.py`, `appraisal_contracts.py`: mixed qualitative experience, current triggers, identity basis, repeated-ground protection and reviewed commit. |
| Memory and continuity | Existing agenda, causal memory, episodes, beliefs and private JSON notebook. Notes are subjective; they cannot establish world events or another NPC's knowledge. |
| Context construction | `cognitive_context.py`, `narrative_context.py`, `runtime.contract_data()`: bounded observer/decision/narrator projections from canonical data. |
| Expression and review | `prompts.py`, `rendering.py`, `narration_repair_input.py`: selected meaning, free expressive wording, factual review and one bounded narration repair. |
| Portrait output | `npc_presentation/`, `core/npc_presentation.py`, `frontend/src/utils/npcPresentation.ts`: free emotion labels, numeric RGB, intensity and optional fictional thought, bound to the final reply hash. |
| Repetition | `narrator/flow.py`, `flow_metrics.py`, `flow_text.py`: existing bounded phrase, opening, closing, gesture, punctuation and rhythm measurements; optional soft guidance. |
| Lifecycle | CHPM state/replay/source retraction, copy/import and narration regeneration already own their respective persistence boundaries. |

The earlier [situation/emotion investigation](emotion-context-research-plan.md)
records implemented scene handoff and state-grounded appraisal work. Its historical
gap descriptions must not be mistaken for current missing functionality. Also reuse
[experience](../chpm-experience.md), [appraisal](../chpm-appraisal.md),
[portrait presentation](../npc-portrait-presentation.md),
[notebook](../npc-notebook.md) and
[regeneration](narration-regeneration.md) contracts.

## Verified engineering limits

- A proposal can add at most two experiences; the core retains up to 128 current
  dimension/subject combinations, with their source-bound event history.
- The model-facing view contains the latest eight dimension records. At most two
  stored explanations are added within 512 extra serialized characters.
- The 30-game-minute horizon marks old appraisals as current-intensity-unknown.
  It does not reduce intensity, forgive an event or imply emotional recovery.
- CHPM dimensions are a bounded engineering vocabulary. The portrait label is
  already free-form, up to 80 characters; its optional fictional thought is up to
  160 characters. The two representations have different owners and meanings.
- Default CHPM input admission is 24,000 characters. The representative two-NPC
  repair from #32 uses 23,375 characters. New context must be budgeted; increasing
  defaults or silently dropping source-bound facts is not the starting solution.
- Repetition analysis already samples up to eight replies, 2,000 characters and
  320 lexical tokens per reply. Soft guidance is at most 1,200 characters and
  respects narration voice, amount, pace, dialogue and deliberate callbacks.
- Free narration and stored history preserve expressive wording. Legacy voice-tag
  normalization and repetition-cleanup helpers are not proof that active narration
  is filtered. Preserve the fidelity tests when inspecting those call sites.

## Findings and questions to reproduce

These are separated deliberately: a visible code limit is not a demonstrated
explanation of poor model behavior.

| Observation | Status | Required check before a behavior change |
| --- | --- | --- |
| Recency selects the eight exposed experiences; explanations have another two-entry cap. | Nine-record offline fixture confirms projection omission; separate recall can still retrieve its source. Quality effect unmeasured. | Test relevant context together across projections at the same budget; do not claim complete forgetting from the cap alone. |
| Reason admission examines only the first two candidates, even after a budget rejection. | Offline fixture confirms a shorter third reason fits: two reasons need 468 of 512 extra characters, but only one is admitted. | Add a regression before backfilling within the existing count/serialized-size/source limits in `narrative_context.py`. |
| Experience updates require current observed grounds; repeated roots cannot refresh them. | Intended protection; recall-only internal reappraisal is restricted. | Distinguish retained feeling, genuinely new consequences and internal reappraisal. A changed interpretation is not a new world event. Any extension needs a source/authority/lifecycle contract before validation changes. |
| Feeling, attempted regulation and outward expression are distinguished in prompts, but their handoff is largely textual. | Existing capability; sufficiency unmeasured. | Paired open/restrained-expression scenes; find which information is actually lost before proposing another field. |
| Portrait output requests one dominant overall feeling. | Intended display simplification. | Preserve underlying mixed experience and private thought without treating that single UI label as complete psychology. |
| The #32 live model translated technical voice tokens despite receiving the catalog. | Observed model formatting failure. | Exercise actual narration, repair and TTS/rendering paths with literal tokens; separate protocol formatting from emotional quality. |
| Earlier prose and delivery cues remain in narration history. | Intentional fidelity behavior. | Measure imitation on matched histories. Reuse #24 guidance; do not strip stored prose or erase purposeful emotional callbacks. |
| CHPM review primarily checks meaning, facts, agency and evidence. | Existing contract. | Detect whether an emotional mismatch can pass while a grounded expressive variant remains allowed. Do not enforce one required display. |
| Simplified, partial and inactive modes have distinct authority boundaries. | Existing tested behavior. | Preserve confirmed psychology and unknown-current labels; presentation availability alone cannot authorize new actions. |

## Reading program and evidence standard

Two full source files have been supplied. Reading and application are different
tasks: extraction, table-of-contents inspection and a chapter summary do not count
as reading an entire book.

| Source | Edition/identity | Current reading status |
| --- | --- | --- |
| James J. Gross, ed., *Handbook of Emotion Regulation* | Second edition, 2014; 689 PDF pages, 36 chapters. This is not the 2024 Gross/Ford edition. | All 36 substantive chapters reviewed, with chapter notes and page coverage recorded separately. Captions and in-text descriptions were read; experimental pictures, graphical data and reference lists were not independently assessed or verified. |
| Carroll E. Izard, *The Psychology of Emotions*, supplied Russian text | 683 PDF pages, 17 chapters; exact translation/imprint not yet established. PDF metadata is unreliable, so identity is checked against the visible title and contents. | All 17 substantive chapters, suggested-reading descriptions and epilogue reviewed, physical PDF pages 14–638. General bibliography begins on page 638 and is not independently verified. Experimental images and graphical measurements were not independently assessed. |
| Remaining titles in the supplied bibliography | No full texts supplied so far. | Bibliographic leads, not completed book reviews. They do not block work with the two available books. |

For every chapter, record page coverage, the author's claim, evidence type,
limitations, agreement/conflict with other sources, relevance to an existing code
owner, a proposed behavioral test and an adoption decision. Separate main-text
coverage from references, figures requiring visual inspection and unreviewed pages.

Read all substantive chapters of both supplied books. Lower-priority biological,
developmental and clinical sections still receive a coverage record; their likely
engineering outcome may be explicitly **do not implement**. Do not turn population
findings, historical diagnostic claims or correlational evidence into deterministic
rules for a particular NPC.

Supplement older books with relevant primary research. Initial references:

- Gross (1998), [experience versus expression under different regulation strategies](https://pubmed.ncbi.nlm.nih.gov/9457784/): abstract reviewed; not the full study.
- Scherer and Moors (2019), [event appraisal and component differentiation](https://doi.org/10.1146/annurev-psych-122216-011854): abstract and manuscript opening/contents reviewed; full paper not yet reviewed.
- Barrett et al. (2019), [limits of inferring emotion from facial movements](https://pmc.ncbi.nlm.nih.gov/articles/PMC6640856/): abstract and opening reviewed; full review not yet read.
- Scherer (2009), [dynamic emotion architectures and virtual agents](https://pmc.ncbi.nlm.nih.gov/articles/PMC2781886/): abstract and initial conceptual discussion reviewed; a theoretical source, not validation of this engine.

Chapter 1 of Gross supports distinguishing regulatory goals, attempted strategies
and actual outcomes. Regulation can increase or decrease positive or negative
feelings for different purposes. Strategy effects depend on context; the chapter
explicitly cautions against declaring one strategy universally better. These are
useful test distinctions, not a mandate to make every character calm or therapeutic.

Book text remains research input. Production prompts should contain small original
contracts, not reproduced chapters, a mandatory diary layout or a growing library
in every request. Main-text review is complete; empirical claims remain limited
by the quality, scope and age of the underlying evidence.

## Candidate mechanisms from the completed reading

These are engineering candidates, not new persisted fields or universal rules.
The following distinctions follow from the completed comparison of the supplied
books. They define evaluation contrasts rather than automatic psychological laws.

| Mechanism | Existing owner and smallest useful application | Evidence limit and behavioral contrast |
| --- | --- | --- |
| Personal appraisal | Keep the observed event, a relevant expectation and the NPC's stakes together in `appraisal.py` / `motivation.py`. | Chapters 1–2 support contextual valuation, not a fixed event-to-emotion lookup. The same setback may threaten one goal and advance another. |
| Regulation goal, attempt and outcome | Reuse the selected intention and its explanation to convey what the NPC tries to change or conceal; validate the observed result separately. | Chapters 1, 5 and 8 distinguish these concepts. Wanting to calm down or look calm does not prove either result. |
| Immediate attention versus lasting interpretation | Keep a temporary detour distinct from resolution through the existing agenda, causal continuity and experience projections. | Chapters 2–3 and 8 describe different effects in laboratory tasks; they do not give an NPC recovery timer. Returning to a topic can reveal an unresolved cause without creating a new world event. |
| Available skill versus spontaneous choice | Evaluate whether an NPC chooses a plausible coping action for its own reasons, as well as whether it follows an explicit instruction. | Chapters 4–5 and 8 distinguish instructed performance from spontaneous engagement. A successful instructed test alone does not establish initiative. |
| Reliability and competing goals | Reuse source-linked relationship beliefs, observed kept/broken promises and ongoing agenda when weighing options. | Chapters 6–7 and 9 describe task-dependent choices. Rejecting an unreliable offer can be coherent rather than a failure of self-control. |
| Feeling, display and consequential action | Preserve mixed experience while allowing civil speech, refusal, cooperation or strong expression when grounded. | Chapters 1 and 9 do not support a one-to-one mapping. Neither politeness nor a portrait color determines an internal feeling or a world action. |
| Original trigger and maintaining significance | Keep a relevant unresolved promise, expectation or relationship concern available through existing continuity owners. | Chapters 15, 25 and 31 distinguish continuing meaning from a fresh external incident. Relevant recurrence must not be confused with duplicated prose. |
| Interpersonal regulation | Another NPC's offered help is an observable input to this NPC's fallible interpretation, not a shared emotional state. | Chapters 14–18 allow different responses to the same attempt. Support offered, received and effective are distinct. |
| Internal reappraisal | First reproduce whether retained context and existing intentions suffice. Specify an explicit source contract if persistence needs an extension. | Handbook chapters 21, 23 and 27 and Izard chapters 1–3 and 13 allow internal sources; the current observed-trigger rule is an engineering restriction, not a psychological law. Preserve anti-duplication and timeline authority. |
| Enduring relationship and immediate experience | Reuse relationship beliefs and shared causal history alongside the current experience estimate. | Izard chapter 17 and Handbook chapters 15 and 17 allow disagreement within a valued relationship. One argument cannot automatically erase attachment; one smile cannot repair trust. |
| Positive engagement and ordinary initiative | Include established interests, quiet achievement and meaningful conversation in the existing option/appraisal evaluation. | Izard chapters 4–8 distinguish interest, activation, pleasure and joy. No mandatory novelty, enthusiasm or notebook write follows. |

Use these distinctions to design comparisons before editing prompts. A professional
character can feel strongly without abandoning expertise; a cooperative character
can refuse; a coping attempt can fail. Do not make every NPC introspective, articulate
or therapeutically skilled. Routine emotion need not produce a new state record,
notebook entry, gesture or explicit explanation on every turn.

The supplied bibliography includes competing theoretical schools. Review Izard's
discrete-emotion account against the Handbook's appraisal and construction accounts
without presenting their disputed mechanisms as settled facts. Prefer their shared
testable requirements: context, individual significance, multiple response channels
and continuity. Do not add brain regions, neurotransmitters, diagnostic labels,
willpower/glucose counters or fixed strategy thresholds as simulated state.

## Proposed work sequence

### 0. Freeze the baseline and finish research

Record the exact base, effective settings, request envelopes and known failures.
Complete the supplied-book reading ledger and cross-source synthesis before
finalizing new persisted concepts. Keep this plan revisable as evidence develops.

Baseline checks already run with isolated databases and mocked providers:

- Emotion/appraisal/narration/presentation/voice selection: **139 passed**.
- Repetition runtime/regeneration/lifecycle and context/observation boundaries:
  **101 passed**.
- No live endpoint was called. These 240 existing tests establish a software
  baseline, not improved emotional writing.

The substantive-text reading is complete: 36 Handbook chapters, 17 Izard chapters
and the epilogue. Both chapter maps and explicit adoption/exclusion decisions are
in the research companion. One additional offline diagnostic passed, confirming
projection omission and an avoidable reason-packing gap. It is not a live-model
or emotional-quality result.

### 1. Build matched reproductions inside existing evaluation owners

Extend CHPM evaluation fixtures and the existing narration-flow evaluator. Capture
the observer input, selected intention, projected experience, final prose, portrait
metadata, review result and actual committed state. Technical diagnostics remain
bounded and private; do not request hidden model reasoning transcripts.

Use the current matrix/appraisal paths and full VN integration for claims about
`cognition.deliberate()`. The older paired-dialogue and trajectory tools call
`cognition.decide()` and do not exercise the full current experience/agent path.
Authored long histories must be labelled as authored, separately from consecutive
generated turns. Reuse the existing harnesses and extend their current owners.

Separate:

1. a source/context handoff failure;
2. an invalid or unsupported model proposal;
3. a source-valid but psychologically weak interpretation;
4. expressive flattening during narration or review;
5. presentation/voice formatting failure;
6. a coherent restrained reaction that should remain valid.

### 2. Repair demonstrated context/continuity gaps in CHPM

The first implemented slice is reason backfill in
`narrative_context.py`: try a shorter eligible candidate when an earlier reason
does not fit, while preserving the two-admitted-reason and 512-extra-character
limits. Verify exact limits, deterministic priority, escaping, mixed channels,
historical status and observer locality. Do not change prompts, schemas or
experience selection merely to make this packing regression pass. Four new
regression cases failed on the baseline; all six packing tests pass after the fix.

Start with existing experience and causal-memory projections. Evaluate a bounded
selection of relevant unresolved circumstances alongside current triggers instead
of simply increasing the number of exposed entries. Preserve the full canonical
history and explicit omission counts. Current facts outrank stale recollections;
remembering a feeling does not establish its current intensity.

Keep personal stakes and causes available together. Preserve distinct emotions,
needs, relationship beliefs, intentions and authored traits. Empty appraisal output
must remain unassessed, not calm. Keep observer scope, time and source-retraction
rules. No new memory store or extra extraction request is planned.

If selection changes, the appraisal and narration views must use consistent record
bindings: `already_supports_states` must still identify the evidence it describes.
Context selection is a read-only projection. Selecting an older cause must not
refresh its timestamp, intensity or root evidence. Test exact-fit budgets, omitted
entries, ties and an unavailable/retracted source, including the repair envelope.

### 3. Improve regulation and expression at the existing handoff

Test what the current selected plan and experience explanation can already convey.
Reuse them first. Add a small optional structured field only if a reproduction
shows necessary information cannot survive through existing owners; specify its
source, lifetime, uncertainty, admission and legacy behavior before implementation.

An attempted strategy is not a successful outcome. A composed face does not prove
weak feeling. A strong feeling does not compel loss of control, a particular
gesture, a relationship change or a world action. An NPC may act independently
while leaving the player's decisions and private state to the player.

### 4. Integrate narration, presentation and repetition boundaries

Use the existing CHPM narrator/reviewer contract and #24 flow measurements. Keep
explicit emotions and character-specific voices possible; avoid quotas on tears,
gestures, pauses or questions. Add no competing global emotion prompt.

Verify literal voice tokens through actual consumers. Preserve prose and unknown
markup rather than introducing an unreviewed translation dictionary or silently
rewriting stored narration. Coalesce any necessary contract correction within
existing bounded repair behavior; do not add retry-until-good requests.

Portrait metadata remains display data tied to the accepted reply. Respect enabled
thought/palette settings and current source hashes. Do not turn UI intensity or RGB
into a causal emotional score, or leak private notebooks to other NPCs.

### 5. Validate behavior and close a bounded PR

Run focused regressions, then the appropriate complete backend checks and optional
Concordia compatibility. Run the full frontend suite before any frontend push.
Review the complete diff against the frozen base, update documentation, publish
neutral technical commits and await CI/Security on the exact final head.

Live comparisons begin only after a fresh user-supplied endpoint is available.
Prepare the runner first; do not reuse retired URLs. Compare baseline and candidate
from independent copies of the same before-turn snapshot with matching histories,
settings and sampling. Record seeds where supported, physical requests, tokens,
latency, failures and unrun cases separately. Start with a small paired smoke set,
then expand to multi-turn cases under an explicit request/deadline envelope.

## Behavioral matrix and acceptance criteria

Case families derived from the completed reading:

1. One event has different personal significance for different NPCs.
2. One feeling is expressed openly or restrained for grounded different reasons.
3. The same calm display coexists with different private experiences.
4. A regulation attempt succeeds, partly succeeds or fails without an invented event.
5. An unresolved cause remains relevant after an unrelated detour.
6. Offered help differs from completed help; completed work need not erase hurt.
7. New evidence can change an appraisal without rewriting the character card.
8. Mixed feelings and competing goals remain possible without forced indecision.
9. More than eight retained experiences and tight context budgets expose selection loss.
10. Repeated reminders do not become independent grounds for escalation.
11. Technical failure or provider refusal preserves the last validated state.
12. Multiple NPCs preserve separate voices, knowledge and player agency.
13. Curiosity and quiet satisfaction support sustained work without forced novelty.
14. Enduring care permits disagreement without an automatic relationship reset.
15. Self-blame and figurative or negated language cannot rewrite canonical events.

Cover CHPM off/shadow/live, partial/inactive/simplified paths; notebook and semantic
recall on/off; normal/streamed/repaired/regenerated replies; short/long histories;
reload, source edits, copy/import, Undo and Chronicles. Notebook persistence outside
story rewind remains distinct from source-bound emotional-state rewind.

Use existing English/Russian evaluation and multilingual flow fixtures. Add Arabic
and East Asian handoff cases where the affected path warrants them. A full Cartesian
product is unnecessary; every risky boundary combination needs explicit coverage.

Human assessment should consider personal relevance, continuity, individuality,
regulation/expression coherence and player agency. Repetition metrics supplement
that review. Fewer gestures, valid JSON, accepted citations or a particular dominant
label do not independently establish improvement. Retain unexpected coherent
responses and report the limits of small live samples.

## Budget and compatibility gates

- No additional default model request or automatic increase in saved limits.
- New CHPM work obeys the module's existing mode, controller and commit boundaries.
- Preserve current facts, identities, source roots and private-memory ownership.
- Any additive saved field needs legacy load/copy/export/rewind checks. Bump a
  schema version only for an actually incompatible data-shape change.
- A failed/oversized/truncated request cannot reset emotion or publish partial notes.
- Keep compact modules and neutral commits; collect prompt-only edits in the final
  `prompt tuning` commit for the implementation wave.
- Exclude private traces, uploaded book text, endpoints and session excerpts from
  GitHub payloads. Publish only original technical synthesis and necessary tests.

## Ready-to-implement gate

Production implementation starts after all substantive chapters of both supplied
books have been reviewed and the cross-source synthesis updated,
the main reproductions distinguish missing context from model judgment, and the
smallest compatible change has an identified existing owner and measurable outcome.
The reason-backfill defect now has that evidence and owner. Broader psychological
quality and relevance-selection changes still need matched current-path results.
The first PR should close the demonstrated gaps, not promise a universal theory of
emotion or expand into model training and a complete psychological simulation.

## First PR completion boundary

The implementation PR should contain the matched reproductions, the smallest
demonstrated CHPM continuity/handoff repairs, necessary narration/presentation
integration changes, focused lifecycle regressions and original technical notes.
Each proposed mechanism needs one of three recorded outcomes: already covered,
demonstrated gap fixed, or deferred with an explicit reason. Research does not
automatically require a code change in every layer.

Before publishing, map every issue #33 work item to code/tests or a documented
limitation. Check causes, progression, individuality, expression, repetition,
memory, presentation and bounded diagnostics separately. Preserve CHPM-off behavior
and distinguish unchanged baseline checks from new regression and live results.
Do not describe model-level psychological quality as solved by passing contracts.

## Current implementation and remaining gates

- Implemented reason backfill inside the existing projection; count, serialized
  size, source age, ordering and canonical data remain unchanged.
- Added handoff regressions through cognitive packing, narration, review, repair,
  load and source retraction, including historical status after a continuity gap.
- Added the opt-in [emotion matrix suite](../chpm-emotional-evaluation.md): 24
  authored contexts / 12 English/Russian pairs, including one/two NPCs and a
  forty-entry detour. These are not generated multi-turn trajectories.
- Added the bounded experience projection to existing proposal/repair audits;
  full private notebook content remains outside that audit allowlist.
- Broader relevance selection, persistent internal reappraisal and new structured
  regulation fields remain conditional. The current reproductions do not justify
  those runtime changes. Existing narrator/reviewer contracts already distinguish
  feeling, attempted regulation and display; no prompt edits are justified yet.
- A fresh provider comparison, generated multi-turn evaluation, actual voice and
  portrait observation, and final issue coverage review remain open. Do not close
  issue #33 or claim emotional-quality improvement from the offline results.

Local implementation validation: **1,740** module/consumer tests and **155**
cross-module integration/security tests passed. Full backend/script Ruff checks
and formatting passed; mypy reported no issues in **1,049** backend source files.
These are offline checks with mocked providers, not a live emotional-quality score.
