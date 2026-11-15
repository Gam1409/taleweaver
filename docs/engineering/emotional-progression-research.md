# Emotional progression: evidence and engineering decisions

Research companion to the [issue #33 work plan](emotional-progression-issue-33.md).
Baseline: `37c4052f91e54ab16325a2bbc1e4f2fdb20a7a52`.
This document contains original technical synthesis, not copied source material.
Research preceded production edits. The first implementation now backfills bounded
stored explanations; the other candidate mechanisms remain subject to the gates
below. This is not a claim of measured emotional-quality improvement.

## Coverage and confidence

The supplied *Handbook of Emotion Regulation* is James J. Gross's **second
edition, 2014**, with 36 chapters and 689 PDF pages. All 36 substantive chapters
have been reviewed, including their conclusions, notes and textual discussion of
figures and tables. Printed chapter ranges below include references; the main
text usually ends earlier. Reference lists were not independently verified.
Experimental pictures, diagram geometry and graphical measurements were not
independently assessed. This is a main-text review, not a visual/data replication.

The supplied Russian Izard text has 683 PDF pages. All 17 substantive chapters,
their suggested-reading descriptions and the epilogue have been reviewed.
The general bibliography begins on physical PDF page 638; its entries and cited
works have not been independently verified. Captions and textual discussions
were read; experimental images and graphical measurements were not independently
assessed. The exact translation/imprint has not been established from reliable
publication information. Its PDF metadata cannot identify the edition.

The other bibliography entries are research leads. Their full texts have not
been supplied or reviewed. Completion here means review of the substantive text
of these two supplied books, not the entire bibliography or replication of their
experiments. Engineering proposals still require baseline reproductions.

Private chapter ledgers record coverage, claims, limitations, applications and
candidate tests. They and the uploaded source files do not belong in the repo.

## What the reading changes about the problem

The target is coherent character behavior. More emotion labels, longer prompts,
more frequent notebook writes or a higher reaction intensity would not establish
that improvement. Relevant distinctions already fit existing CHPM owners:

| Distinction | Engineering consequence |
| --- | --- |
| Event versus personal meaning | The same public event can have different implications for different goals, expectations and relationships. Interpretation remains subjective. |
| Original trigger versus maintaining concern | A resolved immediate obstacle can leave an unresolved promise, loss or trust concern. Preserve relevant context without inventing another event. |
| Experience versus outward display | A civil response can coexist with anger; a smile can coexist with distress. Presentation must not reset experience. |
| Goal versus attempt versus outcome | Wanting reassurance, asking for it, receiving it and actually feeling reassured are separate outcomes. |
| Action tendency versus chosen action | Fear does not require retreat; anger does not require aggression; desire does not execute a world action. |
| Available skill versus spontaneous use | Following an explicit coping instruction is weaker evidence than choosing a fitting action without that instruction. |
| Short-term detour versus resolution | Distraction can change attention while the unresolved concern remains relevant later. No recovery timer follows. |
| Recurrence versus copied prose | Returning to the same concern can be coherent. Repeating the same gesture or sentence need not be. |
| Public signal versus another actor's inference | An NPC observes speech and actions, then interprets them. It cannot read another NPC's notebook or experience state. |
| Emotion vocabulary versus complete psychology | A dominant portrait label is a display simplification; one label cannot replace mixed experience, motives and beliefs. |
| Enduring relationship versus momentary feeling | Anger need not erase attachment, and a pleasant exchange need not repair trust. Reuse relationship owners separately from experience. |
| Felt responsibility versus actual causality | Self-blame, an accusation and validated responsibility differ. Subjective interpretation cannot rewrite committed events. |

Professional competence does not imply weak feeling. Strong feeling does not
imply incompetence. A restrained character need not explain an elaborate coping
strategy, and an expressive character need not lose agency or expertise.

## Handbook chapter map

This map records the useful distinction or explicit exclusion from each chapter.
Human clinical, developmental and biological findings are not executable NPC laws.

| Chapter; printed pages | Application or exclusion |
| --- | --- |
| 1. Foundations; 3–22 | Distinguish regulation goals, strategies and outcomes; regulation can increase or decrease either pleasant or unpleasant feeling. |
| 2. Valuation; 23–42 | Consider current input, personal history and goals together; no simulated neural-region variables. |
| 3. Temporal dynamics; 43–57 | Distinguish immediate attention shifts from lasting changed meaning; no fixed decay curve. |
| 4. Dysregulation; 58–75 | Duration, intensity and spontaneous strategy use are different; do not infer a disorder. |
| 5. Implicit/explicit regulation; 76–92 | Permit habitual action without compulsory introspection; instruction-following does not prove initiative. |
| 6. Delay discounting; 93–110 | Preserve competing near/future goals without requiring one to win. |
| 7. Delay of gratification; 111–125 | Reliability and opportunity matter; refusing an unreliable promise can be reasonable. |
| 8. Regulation choice; 126–139 | A strategy must fit accessible options and personal purposes; choice does not guarantee success. |
| 9. Decisions; 140–156 | Personal meaning can affect the selected action, not only its wording; civility and agreement remain separate. |
| 10. Effortful control; 157–172 | Initiative and restraint both deserve evaluation; obedience is not a general quality score. |
| 11. Family socialization; 173–186 | Authored learning history can inform style; offered support differs from received support. |
| 12. Adolescence; 187–202 | Desired emotion differs from actual emotion; no age-to-strategy lookup. |
| 13. Aging; 203–220 | Use supported time horizons and stakes; age alone does not establish emotional capacity or style. |
| 14. Social baseline; 221–236 | An ally's actual availability and reliability matter; proximity is not automatic reassurance. |
| 15. Attachment; 237–250 | Hurt, closeness, forgiveness and restored trust are separate; reuse authored beliefs rather than attachment meters. |
| 16. Evaluation/attitudes; 251–266 | Ambivalence can coexist with a chosen action; negated feelings must not become affirmative facts. |
| 17. Couples; 267–283 | A soothing attempt can feel dismissive; preserve separate actors and interpretations. |
| 18. Culture; 284–304 | Use authored world norms and individual commitments; infer neither temperament nor restraint from a name or language. |
| 19. Temperament; 305–320 | Tendencies bias response without fixing action; no mandatory mixing weights. |
| 20. Individual differences; 321–345 | Measure produced behavior separately from self-report and valid JSON. |
| 21. Desire; 346–360 | Distinguish wanting, willingness, chosen action and outcome; internally generated change raises a source-contract question. |
| 22. Emotion goals; 361–375 | A character may seek, preserve or conceal a feeling for an instrumental purpose. |
| 23. Self-awareness; 376–392 | Self-image and expected reception can matter; imagined judgment is not access to another mind. |
| 24. Anxiety; 393–412 | Strategy selection, implementation and outcome differ; clinical correlations do not diagnose an NPC. |
| 25. Mood; 413–427 | Repeated concern differs from repetitive model prose; a positive moment need not erase hurt. |
| 26. Substance use; 428–446 | Expected relief differs from actual effect; exclude clinical and pharmacological simulation. |
| 27. Construction account; 447–468 | Labels and gestures do not have one fixed meaning; engineering layers do not claim brain modularity. |
| 28. Regulation therapy; 469–490 | Values-guided action can coexist with distress; do not impose a therapist voice or worksheet. |
| 29. Dialectical behavior therapy; 491–507 | Separate cue, interpretation, urge, action and aftereffect; no mandatory clinical taxonomy. |
| 30. Attention modification; 508–528 | Measure context delivery and behavioral transfer separately; hiding inconvenient facts is not a valid improvement. |
| 31. Affect regulation training; 529–547 | Distinguish original trigger from a current maintaining cause; insight does not establish recovery. |
| 32. Mindfulness; 548–570 | Noticing a feeling need not endorse its interpretation or execute its urge; no compulsory coping speech. |
| 33. Gene expression; 571–585 | Exclude gene, inflammation and illness updates; the chapter itself identifies untested causal links. |
| 34. Socioeconomic context; 586–595 | Accessible options matter; background does not establish psychological deficit or require acceptance of injustice. |
| 35. Cardiovascular risk; 596–612 | Exclude individual health predictions from group associations; negative feeling is not itself pathology. |
| 36. Self-regulation failure; 613–628 | Changed priorities and failed implementation differ; do not implement a finite willpower resource. |

The clinical chapters are particularly useful as constraints on overclaiming.
Treatment packages, self-report associations and population differences do not
validate an individual causal rule or a fictional character's diagnosis.

## Izard chapter map and comparison

| Reviewed chapter; physical PDF pages | Useful comparison | Limit |
| --- | --- | --- |
| 1. Origins/functions; 14–50 | State, enduring tendency and learned expressive style differ. Thoughts and remembered images can matter without a fresh external event. | Differential-emotions theory is a theoretical position; biological and clinical generalizations require independent checking. |
| 2. Definitions and personality; 51–102 | Agency, controllability and responsibility affect appraisal; mixed feelings and action tendencies need not collapse into one action. | No mandatory ten-emotion list, arithmetic emotion mixtures or authenticity detector follows from the historical review. |
| 3. Consciousness and cognition; 103–149 | Feeling, noticing and naming are different; visible expression can end before experience. | Consciousness theories do not establish LLM consciousness. Old physiological accounts do not justify runtime mechanics. |
| 4. Interest and activation; 150–176 | Curiosity, attention and general activation differ; eager anticipation need not mean fear. | No fixed novelty threshold or facial authenticity detector. |
| 5. Development of interest; 177–208 | Established interests can sustain ordinary work and initiative without a new dramatic stimulus. | Developmental examples do not prescribe a character's skills or personality. |
| 6. Pleasure and joy; 209–240 | Relief, pleasure, pride and joy differ; positive experience can coexist with unresolved hurt. | A smile or one success does not establish global recovery. |
| 7. Empirical study of joy; 241–274 | Humor, social laughter, reported mood and performance are different measures. | Associations do not prove benefits for every task or individual. |
| 8. Surprise; 275–281 | An expectation violation can redirect attention before its personal significance becomes clear. | No mandatory positive/negative valence or persistent surprise state. |
| 9. Sadness; 282–305 | Loss can matter while useful work continues; offered support differs from resolution. | Sadness is not automatically dysfunction or a request for treatment. |
| 10. Grief and depression; 306–346 | Loss of a role, relationship or possibility can matter differently; feelings need not follow a fixed sequence. | No clinical diagnosis, universal stages or health-risk prediction. |
| 11. Anger; 347–390 | Obstruction, attributed intent, anger, assertion and aggression differ; injustice may remain after an obstacle clears. | Anger does not require violence, guilt or an immediate calm response. |
| 12. Disgust and contempt; 391–424 | Subjective rejection or perceived contamination differs from actual item/body state. | Neither a metaphor nor a hostile image authorizes a physical mutation or action. |
| 13. Fear and anxiety; 425–476 | Believed threat, actual danger and protective choice differ; competence can coexist with fear. | No fixed fear script, automatic retreat or access to another actor's private concerns. |
| 14. Embarrassment; 477–499 | Situational discomfort, enduring shyness, desire for contact and skill differ. | Quietness does not prohibit initiative or prove another observer's judgment. |
| 15. Shame; 500–544 | Self-image, self-report, public exposure and another person's evaluation differ. | Historical clinical and cultural generalizations are not authored character norms. |
| 16. Guilt and conscience; 545–612 | Felt responsibility, actual responsibility, apology, repair and forgiveness differ. | Do not infer morality from obedience or adopt historical diagnostic assumptions. |
| 17. Love; 613–635, epilogue 636–638 | Enduring attachment permits disagreement and mixed feelings; reliable support differs from mere proximity. | Kinship hierarchies, gender roles and retrospective anecdotes are not universal causal laws. |

There is agreement on context, individual history, motivation and multiple
response channels. There is disagreement on universal emotion programs, the
priority of cognition and the relation between expression and experience.
Keep those disagreements visible. The engineering model needs observable
contracts, not a claim that the theories have been reconciled.

### Cross-source decisions

The books support distinguishing a useful set of engineering observations, while
disagreeing about their psychological mechanisms. This does not establish that
CHPM implements a human mind.

- **Adopt as evaluation distinctions:** personal significance; competing goals;
  feeling, noticing and naming; action tendency versus selection; strategy
  attempt versus outcome; display versus experience; short detour versus lasting
  changed meaning; enduring relationship versus momentary response.
- **Reuse existing owners:** authored tendencies, source-bound experience,
  subjective beliefs, agenda, causal memory, intentions and the private notebook.
  A book's additional term does not by itself require another saved variable.
- **Keep conditional:** persistent internal reappraisal, relevance selection and
  structured regulation output. Each needs a demonstrated contract gap before
  introducing a new field or changing admission.
- **Exclude from this PR:** universal emotion programs, fixed developmental or
  grief stages, a ranking of relationships by kinship, clinical classification,
  simulated brain regions, health effects and finite willpower resources.

Curiosity, quiet satisfaction, humor and sustained task engagement belong in the
evaluation alongside distress and conflict. A quiet authored profile can still
initiate a valued conversation. Emotional language also needs contextual reading:
negation, eager anticipation and a metaphor about contamination cannot be mapped
directly to fear, an affirmative feeling or a physical state change.

A model's plausible description is an observable output. Its self-report does
not establish consciousness, a felt experience or model-weight learning. Notebook
continuity can support a character's behavior without making those claims.

## Checks against later research

These are targeted checks of primary-publication abstracts and reported results,
not full-paper reviews or an exhaustive contemporary literature review.

| Source | Result relevant to this decision | Consequence and limit |
| --- | --- | --- |
| [Gross, 1998](https://pubmed.ncbi.nlm.nih.gov/9457784/) | In the reported film task, suppression and reappraisal both reduced expressive behavior, while experiential/physiological outcomes differed. | Reduced display cannot establish reduced feeling. One instructed task does not rank strategies for every context. |
| [Hagger et al., 2016](https://doi.org/10.1177/1745691616652873) | A preregistered 23-lab replication, N=2,141, estimated d=0.04 with a confidence interval spanning zero. | The tested resource-depletion prediction was not supported; no finite willpower counter. This does not show fatigue never matters. |
| [Vohs et al., 2021](https://doi.org/10.1177/0956797621989733) | A preregistered 36-lab project, N=3,531, found no confirmatory depletion effect; exploratory findings were smaller. | The older strength-resource account is unsuitable as a settled simulation law. Confirmatory and exploratory results remain distinct. |
| [Watts, Duncan and Quan, 2018](https://doi.org/10.1177/0956797618761661) | Associations between early waiting and later achievement shrank substantially after controls; behavioral associations were small. | Do not turn a waiting choice into a stable quality or future-success score. The study is observational, not proof of a particular alternative cause. |
| [Kidd, Palmeri and Aslin, 2013](https://pmc.ncbi.nlm.nih.gov/articles/PMC3730121/) | A small experiment, N=28, found waiting varied with demonstrated environmental reliability. | Include reliability contrasts in evaluation. The sample does not supply universal trait or timing parameters. |
| [Barrett et al., 2019](https://pmc.ncbi.nlm.nih.gov/articles/PMC6640856/) | The review reports substantial variation and insufficient reliability/specificity for diagnostic emotion inference from facial configurations. | A gesture, portrait or smile is not a mind-reading interface. Facial behavior still carries contextual social information. |
| [Coles et al., 2022](https://doi.org/10.1038/s41562-022-01458-9) | The preregistered Many Smiles study, N=3,878 across 19 countries, found effects for some instructed facial tasks, with less conclusive pen-task results. | Do not say facial feedback never exists; equally, a portrait change cannot force canonical happiness. Task effects do not define a game-state rule. |

Candidate-gene rules, diagnostic inference, health-risk simulation and automatic
biological feedback are excluded from this PR. Claims about those mechanisms do
not need to become runtime dependencies. Any later proposal to implement one
would require its own current evidence review.

## Existing source contract: an important scope question

`chpm/experience.py::_resolve()` requires an exact visible citation and a current
observed trigger. `core/experience.py` protects against refreshing or intensifying
an estimate using the same underlying evidence. These protections prevent a
recalled narrative or repeated reminder from masquerading as a new world event.

Human theories in the reviewed material allow feelings to change through recall,
anticipation and reappraisal. Consequently, the current admission rule is an
engineering restriction, not a psychological law. Three cases must stay distinct:

1. **Continuity:** retain a previously assessed feeling or concern, with its real
   timestamp and current-intensity uncertainty. Projection must not refresh it.
2. **New observed consequence:** assess new information with its own valid source.
   A reminder is not automatically independent evidence.
3. **Internal reappraisal:** the character revises the meaning of accessible
   information without claiming the external world changed. Current experience
   admission does not generally authorize recall-only updates of this kind.

The first reproduction should establish whether continuity/context repair is
enough. If a persistent internal-reappraisal feature is needed, specify its
admissible source, causal parent, deduplication, uncertainty, quota, review and
rewind behavior before changing the contract. Do not remove current-source checks
or synthesize fake host observations as a shortcut.

## Deterministic baseline observations

A private offline probe exercised the existing reducer, admission and projection
functions with neutral synthetic observations. Each turn proposed one experience;
no provider was called and no production code changed. The probe passed.

1. **Recency omission is real, complete context loss is not established.** Nine
   valid distinct experience keys leave eight visible records and one explicit
   omission. The first record and its reason disappear from the experience and
   narrator projections while remaining in canonical state. Its source can still
   be retrieved separately by existing episodic recall. The fixture therefore
   establishes a projection limitation, not that the model necessarily forgets
   the incident or chooses an incoherent response.
2. **Reason packing does not backfill.** Three valid stored explanations expose a
   deterministic admission gap: `experience_reasons()` examines only the first
   two candidates. When one fits and the next exceeds the extra budget, a shorter
   third is never tried. In the serialization-boundary fixture, two explanations
   would occupy 468 of the allowed 512 extra characters, but only one is admitted.
   The long strings contain legal quote/backslash characters to exercise JSON
   escaping; this is a packing test, not a sample of emotional prose.

The first production slice repairs the second observation inside
`narrative_context.py`, with regression failures recorded on the frozen base. Keep the
two-admitted-reason cap, 512-character allowance, priority order, source bindings
and read-only behavior. Continue through eligible candidates only until the
admitted count or budget is exhausted. A relevance-selection change needs more
evidence than the first observation supplies.

## Proposed decision order

| Candidate | Decision now | Evidence required before changing behavior |
| --- | --- | --- |
| Add a large general psychology prompt | Exclude | Existing budgets and owners already carry the relevant concepts. |
| Backfill eligible reasons after a candidate exceeds the budget | Demonstrated gap; smallest first fix | Preserve count, serialized-size, ordering, source and lifecycle invariants; add a failing regression before repair. |
| Preserve relevant older concerns in the bounded view | Investigate first | A matched case must demonstrate omission or binding loss under the eight-entry/two-explanation limits. |
| Clarify regulation outcome at the current handoff | Reuse existing fields first | Show that a valid distinction is lost between accepted proposal and narration. |
| Add a persistent internal-reappraisal source type | Conditional, separate contract decision | Show that retained context and current observations cannot express a necessary supported change. |
| Expand portrait emotion taxonomy | No fixed taxonomy needed | Labels are already free-form; verify consumers and literal voice tokens instead. |
| Create another emotion/memory store | Exclude | Existing experience, agenda, causal memory and notebook owners remain authoritative. |
| Use repetition scores to force emotional novelty | Exclude | Evaluate meaningful callbacks separately from copied wording using #24. |
| Add automatic calmness/decay or health penalties | Exclude | Neither source age nor a coping attempt proves that outcome. |
| Require reflective notebook entries | Exclude | Preserve the NPC's chosen JSON organization and ordinary action without mandatory journaling. |

## Evaluation must locate the failure

Capture bounded data at the existing boundaries:

```mermaid
flowchart LR
    O[Allowed observations and personal basis] --> P[Packed CHPM context]
    P --> A[Appraisal and selected intention]
    A --> V[Validation and committed experience]
    V --> N[Narrator and review handoff]
    N --> T[Accepted prose and delivery cues]
    T --> D[Portrait and voice consumers]
```

An omitted concern, an unsupported proposal, an overly generic appraisal, a
flattened narration and a malformed delivery token require different repairs.
Valid JSON, accepted evidence and an attractive portrait do not measure the same
thing as believable emotional progression.

Use the [matched-case specification](emotional-progression-cases.md) in the existing
CHPM matrix/appraisal and VN integration paths. The older dialogue/trajectory
runner does not exercise the entire current deliberation path. A long authored
history is useful for isolation but must not be presented as a generated long
conversation. Retain case outcomes that are unexpected yet coherent.

## Remaining implementation preparation

- The substantive-text reading and cross-source synthesis are complete within
  the coverage limits above. No additional book is required for the first slice.
- Extend the recorded projection/packing observations to matched current-path
  handoffs; establish relevance-selection quality separately from its hard cap.
- Evaluate further changes only after a matched current-path result establishes
  a gap; the first bounded packing fix already has an identified owner and
  regression coverage without an additional default model request.

The 240 passing baseline tests establish existing software behavior. The first
packing repair and opt-in [evaluation suite](../chpm-emotional-evaluation.md) now
have focused offline checks. No emotional-quality result, live comparison or
completion of the broader issue is claimed.
