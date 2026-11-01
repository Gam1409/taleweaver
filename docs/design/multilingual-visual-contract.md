# Multilingual visual contracts across tags, prose and hybrid prompts

Status: proposal for review, not an implementation. Based on main commit 3f46c8bf.
Scope: neutral visual continuity and format-aware scene preparation. Narrative
language, original evidence, existing content-policy/addendum behavior, references,
wardrobe mechanics, UI translation and memory retrieval are outside this change.

## Findings and reproduction

I read the current fidelity, render, staging schema and adapter implementations,
plus the session-language and visual-reliability documentation. I exercised the
actual pure fidelity functions in isolation, without changing repository code or
calling a model. The neutral fixture contains Alex, a blue coat, a bench, a book
and its position on a table: five potential literal anchors. The same facts were
supplied in English, Russian, French, Japanese, German and Polish. Every case was
run through tags, description and hybrid validation.

| Source language | Literal anchors retained | Correct English realization | Realization omitting objects/placement |
| --- | --- | --- | --- |
| English | 5/5 | Accepted | Rejected |
| Russian, Japanese | 1/5 | Accepted | Accepted |
| French, German, Polish | 5/5 | Rejected | Rejected |

These are lexical checks, not live translation or image-quality measurements.
The attachment's reproduction calls literal_diff, not the complete differences
pipeline: it cannot establish that phase B also accepts an incorrect pose. Its
`seated` fixture is outside the persistent staging enum (`sitting`). The example
labelled GOOD is not a controlled complete realization of its own clothing facts.
Also, French `robe de chambre` is not unambiguously `nightgown`; the reproduction
above uses `manteau bleu` / `blue coat` to isolate the actual guard defect.

| Issue | Weight | Verdict |
| --- | --- | --- |
| Non-Latin facts excluded from literal checks | Critical for fidelity coverage | Confirmed; omissions can pass. Pose checking provides only partial independent coverage. |
| Non-English Latin text required verbatim | Critical for multilingual usability | Confirmed; script is not language. Correct translations fail or untranslated words leak through. |
| Translation drift across renders | Noticeable, sometimes material | Synonyms alone may be harmless. Changed object category, color, actor assignment or relation can change images and invalidate comparisons. It does not mutate canonical clothing, inventory or narrator state. |
| Repeated passage parsing | Noticeable cost and variability | Conditional, not universal: source-frame extraction runs only for tracked snapshots with passages at most 16,000 characters. The pose checker is another conditional call. |

English is not generally correct either: exact matching rejects legitimate
paraphrases and can accept a named object inside a negation or on the wrong actor.
The recent script filter was a usability workaround, not a durable fidelity model.
The diagnosis is shared by all three formats, not specific to Neta Lumina.
`docs/diagnostics/visual-fidelity.md` also describes an older pipeline; its statements
about no retry/verification calls and managed-clothing gating need updating later.

## Recommended architecture

Keep an immutable source snapshot, a derived English visual plan, and a compiled
prompt artifact as three separate objects:

    Original completed narration + frozen message-time facts
        -> source fact inventory, IDs, exact original-language evidence
        -> lazy English normalization and bounded final-frame extraction
        -> persisted derived visual plan (independent of output format)
        -> tags / description / hybrid compiler selected by profile
        -> format-specific structural validation and coverage report
        -> existing policy/token assembly and image-provider path

The engine owns IDs, subjects, relations, provenance and authority. The normalizer
translates surface descriptions and extracts explicitly supported ephemeral facts;
it cannot replace canonical presence, possessions or clothing. It receives the
original text, never a translated narrative used as evidence. The plan is an image
preparation artifact and never feeds changes back into gameplay or narration.

Each source fact has an opaque fact ID, subject ID, predicate, value or object ID,
source message/revision or frozen source hash, and evidence when available. Existing
canonical inventory/appearance facts need their actual origin, not an invented
narrative quote. Scene objects without world IDs get snapshot-local IDs; these do
not create world entities or assert identity across unrelated scenes.

For example, the source contains three separate facts: Alex is sitting, Alex is
on object B, and Miki is standing in front of Alex. B has an original source label
and a derived English label `bench`. Translation cannot turn the last relation
into Miki standing on B. Subject and target IDs are copied by the engine, not
accepted from a free-form paraphrase without comparison.

A translation entry contains its source fact ID/hash, English realization atoms,
normalizer version/model identity and a validation status. An atom is a bounded
noun/attribute phrase or a supported predicate, not an unrestricted new scene.
Unknown or ambiguous information stays unknown. Evidence is retained verbatim on
the source side and is not a required substring of the English image prompt.
Session content_language is a hint, not proof of every field's language: imported
world descriptions and names can remain in another language after a language switch.

## Where normalization belongs

| Placement | Advantage | Cost/risk | Decision |
| --- | --- | --- | --- |
| During every narrative extraction | Available before render | Charges non-rendered turns; adds coupling and still misses canonical fields outside staging | Do not make this mandatory |
| First render, persisted | Pay only for used scenes; reusable across formats | Cold latency, cache lifecycle, a bad translation can persist | Recommended |
| Every render without persistence | Simple; can sample new interpretations | Repeated cost and uncontrolled semantic variability | Keep only as a diagnostic comparison path |

Replace the existing first preparation call with one structured normalization call,
including bounded source-frame extraction where needed. Do not add a translation
call before the existing whole-prompt rewriting call and leave both permanently.
The common plan contains sufficient English lexical atoms for all three compilers.
A profile may have an English output vocabulary/capability layer; that is not a
source-language bilingual dictionary. Unsupported model-specific lexicalization
must be reported, not claimed universally valid because it is English.

First iteration: cache the complete message-scoped plan. Cross-message translation
reuse is optional later and must key on unchanged source facts and disambiguating
context, not just equal strings. Never reuse a pose merely because an earlier
message had the same noun. Long passages must follow a documented bounded policy;
no new silent truncation should be introduced.

## Three first-class output formats

| Format | Compiler output | Fidelity contract |
| --- | --- | --- |
| Tags | Comma-separated, profile-supported tags from bound visual facts | Required tag groups/allowed alternatives, explicit count consistency, scope/association capability checks; no mandatory prose phrase |
| Description | Controlled English clauses joining subject, action, object and relation | Required clauses generated from fact IDs; no exact source-language noun matching and no mandatory numeral in fluent prose |
| Hybrid | Relational description plus complementary tags | Coverage across both sections; repeated facts are deduplicated for scoring and checked for contradiction |

Example description: “Alex sits on the bench. Miki stands in front of Alex. A book
rests on the table.” In hybrid mode those relationships belong in the description;
style and supported appearance categories can go in the tag section. We should not
flatten that description into `sitting, standing, bench` and claim equivalent fidelity.

Pure tags have a real expressive limit: global tags do not reliably bind two
outfits or poses to two subjects. Regional/subject conditioning could help, but it
is outside this work. Profiles therefore need explicit output capabilities; they
must not infer these from a checkpoint filename alone. If a required relation cannot
be represented, report incomplete coverage. Strict mode stops before submission;
an explicitly selected limited-coverage mode can proceed with a visible limitation.
Do not silently switch a tags-only checkpoint to hybrid to satisfy the validator.
A staged rollout can first measure this in shadow mode before changing defaults.

Style, mandatory tokens and custom instructions must not silently override source
facts. Arbitrary custom free-form requirements cannot all be proved compatible by
a compiler. They need a separate compatibility result; unsupported combinations
must not receive a blanket fidelity-passed badge. Existing content-policy decisions
remain authoritative and are not bypassed by the new compiler.

## Names and fidelity

Character IDs identify actors; names never define equality. Keep original display
names and aliases unchanged. A stable prompt label or descriptor is image-specific,
not a rename. If a profile needs an English/romanized alias, generate/store it once
with provenance or use an explicit author alias. Do not require names inside tag
prompts when doing so only encourages lettering or unwanted character tags. Alias
collisions remain distinguishable through internal IDs. No RU/FR/CJK-specific
transliteration code or whitespace/case-based identity matching is needed.

Separate three different assurances:

1. Source -> plan: schema, IDs, copied enums, ownership of facts and source evidence
   can be checked deterministically. Translation accuracy and pronoun resolution
   remain semantic model judgments; an exact quote alone is not proof of the event.
2. Plan -> prompt: use a compiler that emits text/tags together with fact-to-output
   provenance. Test that provenance against the actual emitted sections. A model's
   self-reported `covered_fact_ids` alongside arbitrary prose is NOT proof of coverage.
3. Prompt -> image: neither textual coverage nor a correct translation guarantees
   correct rendering. This proposal does not claim image-level fidelity.

Literal equality belongs to IDs, revision/hash fences, canonical enum values,
original evidence and explicitly selected technical tokens. It should not govern
natural-language translations or synonyms. Semantics matter for translated labels,
negation, chronology and actor binding. Mood/style need not preserve exact wording.
Do not count private, absent, unknown or merely provisional facts as required output.
Do not count policy-excluded facts as successful coverage; exclusions have explicit
reasons and follow existing policy without changing it.

A single multilingual normalizer can still mistranslate a fact while preserving
its ID. Runtime validation must label that result structurally validated, not
independently semantically verified. Evaluate translations separately on curated
fixtures; allow versioned correction/re-normalization. An optional cold-cache
semantic audit may be warranted by measured failures, but no mandatory new LLM
verifier on every image is proposed.

## Persistence, determinism and cost

Use a derived cache keyed by session scope, snapshot content/facts hashes, source
revision, target language, schema/normalizer version, model configuration fingerprint
and relevant existing content-policy version. Never put credentials in keys or logs.
The compiled artifact also keys on format, profile/vocabulary version, style, custom
rules and token-assembly policy. Seed/dimensions can vary without forcing translation.
Concurrent first renders share work or use CAS publication; late results cannot
attach to a revised message. Failed/partial plans never become ready entries.

Regeneration, rewind, import and copy must remap references or invalidate the cache.
Historical renders normalize only their frozen historical facts, never current scene
state. Changing model/style does not mutate the original snapshot; it either recompiles
from the same compatible plan or explicitly creates a new derived version.

“Same history always produces the same LLM extraction” cannot be guaranteed, even
at temperature zero. The achievable contract is: the same persisted source revision
and approved derived plan are immutable; the same plan/profile/compiler version
produces byte-identical prompts. A fresh independent extraction is a new derivation,
not a claim of bitwise deterministic semantics.

Current scene preparation uses one adaptation call, possibly one source-frame call,
and possibly one pose-check call per attempt: normally 1–3 calls, at most 5 with the
existing retry. This is separate from turn-time staging.

Target steady state: zero preparation LLM calls on a cache hit, including seed-only
rerenders and format changes supported by the plan. Cold cache: one normalization
call; at most one repair for invalid structure/missing required facts. An optional
once-per-plan semantic audit adds one call, not one per render. Free-form novel style
normalization may create a separately keyed cold artifact; it must not be hidden in
the “zero calls” claim. No millisecond estimate is credible without measuring the
selected Utility model. Track input/output tokens and p50/p95 cold/hit latency.

## Proposed modules and rollout

- New `scene_illustrations/visual_plan.py`: source fact inventory and plan contracts.
- New `scene_illustrations/normalization.py`: one structured English normalization.
- New `scene_illustrations/plan_cache.py` plus model/migration: scoped lifecycle and CAS.
- New `scene_illustrations/prompt_compiler.py`: three renderers and output provenance.
- `fidelity.py`: structural/coverage checks and semantic uncertainty reporting; retire
  script-based `_latin()` decisions as the new path reaches parity.
- `render.py`: normalization/cache/compilation orchestration rather than repeated
  translate-and-check loops. `image_prompt_adapter.py` remains compatible for other assets.
- `frames.py`: reuse bounded extraction contracts in normalization; avoid another
  full-passage parse on every cache hit.
- `image_prompt_rules.py` and profile selection: output capability/lexicon versions.
- Existing snapshot, regeneration and session lifecycle helpers: cache invalidation;
  do not replace the authoritative source/evidence representation.
- Diagnostics and tests: distinguish structural coverage, translation evaluation,
  unsupported format capabilities and actual generation outcomes.

Implement behind a separate preparation-path flag. Compare all three formats on
neutral multilingual fixtures, then shadow-test with configured models. Preserve the
legacy path until English parity and cold/hit behavior meet acceptance criteria.
No policy/addendum changes are bundled. Golden tests must establish unchanged policy
selection/injection decisions; bitwise identical instructions alone cannot guarantee
identical generative behavior, which requires a separate acceptance decision.

## Verification and acceptance

- Matrix: EN/RU/FR plus JA/DE/PL, extended with ZH/KO and mixed-script aliases;
  all three formats; one/two/zero characters; optional/unknown gender and appearance.
- Original evidence remains byte-identical. Correct translation fixtures never fail
  merely because their source script differs. The existing French false rejection
  and RU/JA false acceptance cases must be represented explicitly.
- Mutation tests remove or swap a subject, object, position, relation or attribute;
  corrupted compiler output must fail required-fact coverage/contradiction checks.
- Translation tests deliberately mistranslate a source atom to demonstrate the
  separate semantic failure class; ID coverage must not mark these semantically verified.
- Names: multiple scripts, collisions, CJK without spaces, Unicode normalization,
  and stable IDs across session-language changes.
- Lifecycle: concurrent first render, late result after rewrite, restore, import/copy,
  settings change, interrupted normalization and corrupt cache.
- Determinism: 100 rerenders of the same cached plan/profile yield identical compiled
  prompt hashes and zero normalization calls. Measure new-message semantic fact
  retention separately; do not equate lexical sameness with correct scene continuity.
- Coverage denominator: all eligible required source facts, independent of script.
  Report structural/output coverage, unsupported facts, policy exclusions, semantic
  audit results and unknowns separately. Never improve the percentage by dropping
  non-Latin facts from the denominator.
- Track coverage and false-rejection rates by source-language hint AND output format,
  alongside repair/failure rates, cache-hit rate, tokens, latency and stale-cache rejects.
- Zero false refusals is a finite-fixture acceptance target, not a promise for arbitrary
  language/model combinations. Full test-suite baseline must be measured on the current
  revision; the attachment's roughly 2,615 passing tests is not a verified count here.

No runtime code, prompt behavior, database schema or main-branch publication is
changed by this document. Implementation is a separate step after design approval.


## Staging plan — round 2 supersedes the corresponding sections above

The revised self-contained proposal is [round 2](multilingual-visual-contract-round2.md).
It replaces the earlier full-platform-first staging, required taxonomy and cost
assumptions, and specifies legacy inventory, audit scope and exact lifecycle hooks.

| Stage | Independent deliverable |
| --- | --- |
| 0 | Measured baseline and multilingual/format fixture matrix |
| 1 | JSON-backed immutable English plan bundles, bound output units, structural checks, audit and visible limitations; existing output formats retained |
| 2 | Full format compilers, reusable output provenance and capability profiles |
| 3 | Versioned expansion of the small required set |

Stage 1 does not depend on Stages 2–3. Its release gate and all A–D responses are
specified in the linked document. No implementation or main-branch publication is
part of either design document.
