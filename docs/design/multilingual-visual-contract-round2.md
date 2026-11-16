# Multilingual visual contracts — round 2

**Status:** revised design for discussion, not implementation. Source revision:
`3f46c8bf`. This document supersedes the staging, taxonomy, caching and cost decisions
in round 1. The original proposal remains available as the architectural background.
An independent reviewer checked the Stage 1 integrity/expressiveness boundary and
existing lifecycle hooks; the conclusions are incorporated below.

## Decisions A–D at a glance

| Task | Decision |
| --- | --- |
| A: independent Stage 1 | Yes: deterministic source inventory, persisted English plan and frozen output artifact, structural checks, small assembler, audit, feature flag. No new DB table or full compiler framework. |
| B: audit default | Include an audit in Stage 1; default ON for both mature-marked and neutral snapshots. It checks neutral visual continuity. It does not certify preservation of explicit sexual details; that specialized objective is outside this proposal. |
| C: start small | Adopt the human decision. Known cast, structured clothing tokens, confirmed props and explicit pose/placement edges are required in the plan. Other details are best effort. Unexpressible tag bindings are reported limitations, not automatic render failures. |
| D: old sessions | Derive atoms from frozen JSON, deterministically and lazily. No historical staging re-extraction, bulk backfill or mandatory data migration. Missing fields remain unknown. |

Two distinctions are essential. First, a required source fact can be preserved in
the plan while its expression in global tags remains ambiguous. Second, an LLM
listing a fact ID beside arbitrary text does not prove that the text expresses it.
The design must expose both boundaries rather than call everything “coverage passed.”

## Staging plan

| Stage | Scope and modules | Acceptance | Dependency |
| --- | --- | --- | --- |
| 0: baseline | Current tests; frozen EN/RU/FR/JA fixtures; current output capture for tags/description/hybrid | Record baseline failures and existing language/script defects; no functionality changes | None |
| 1: multilingual seam | New `scene_illustrations/visual_plan.py`, `plan_preparation.py`, `plan_cache.py`; scene-only wiring in `render.py`/`generation.py`; new-path validation in `fidelity.py`; lifecycle hooks and diagnostics | Correct translations no longer fail by script; required atom losses/swaps fail; output limitations are visible; repeated exact artifacts are byte-identical; audit and concurrency tests pass | Stage 0 only |
| 2: reusable realization framework | Full `prompt_compiler.py` renderers for tags/description/hybrid; reusable output provenance; versioned profile capabilities; shared English plan across profile variants | Format changes preserve required facts or report specific limits; compatible format switches do not require renormalization | Stage 1, but not required for its release |
| 3: expanded fact sets | New required-set versions; finer attributes/relations and improved measured model support | New fixture classes pass; old artifacts retain their declared semantics | Stage 1; Stage 2 only for features requiring its capabilities |

**In Stage 1:** fact IDs, English normalization, actual emitted units, one audit per
immutable plan, persistent prompt bytes, write fencing, cache lifecycle, visible
coverage and language-independent structural validation. These are not optional
follow-ups: without them the two critical defects would merely move downstream.

**Deferred by name:** dedicated cache table/migration; three full compiler modules;
general capability-profile framework; full output source-map/provenance tooling;
a new hybrid feature or automatic tags-to-hybrid conversion; cross-message semantic
reuse; zero-call switching among arbitrary new profiles; expanded required taxonomy.
Existing description and hybrid configurations continue to produce their selected
format. “Hybrid deferred” means no new hybrid architecture, not removing the mode
already present in `ImagePromptRules`.

## Stage 1 flow: small, but not an ID sidecar

1. `owned_context` and `require_snapshot` select an authorized, matching historical
   snapshot. Freeze its identity and derive the source inventory in code.
2. On a cache miss, one scene-specific structured preparation call returns English
   realizations of that inventory and bounded output units for the **already selected**
   format. It cannot change subject IDs, item owners, predicates or relation targets.
3. Validate required tuples and unit references. A small assembler emits only the
   accepted units in declared sections, with deterministic ordering and separators.
   It stores the exact resulting artifact; it does not ask another model to rewrite it.
4. Run the existing authorized prompt/token assembly without changing its policy
   decisions. Freeze the body and actual final positive/negative text inputs, including
   prefixes, suffixes and applicable style/workflow additions. Audit the source-to-English
   mapping, units, dispositions and these final strings once for this immutable bundle.
   A contradictory suffix cannot inherit the body's successful audit.
5. Submit those exact audited text inputs through the existing provider path. Compare
   the final mapped text-input hashes before job submission; no additional rewriting or
   double prefix assembly may occur after audit. Unsupported dynamic workflow rewriting
   is a visible unsupported-validation case, not a claim of full coverage. Existing image
   attachment checks remain in force, with the preparation epoch checked for new-path jobs.

Stage 1 uses a **format/profile-specific plan bundle**: source atom graph, English
realizations, selected-format units and frozen artifact. This intentionally narrows
round 1's fully format-independent plan. A different profile/format creates a new
bundle and may need cold preparation/audit. Separating reusable English meanings
from arbitrary profile realizations belongs to Stage 2.

The tiny assembler is unavoidable minimum plumbing, not the deferred three-compiler
framework. Tags join validated tag units; description joins sentence units; hybrid
keeps the existing description/tag sections. It does not invent lexical mappings or
translate through hand-written language dictionaries. Unit-to-atom bindings are
internal contract data; full provenance tooling is deferred, but the minimum linkage
needed to inspect what was actually emitted cannot honestly be deferred.

An output unit records the atom IDs, copied subject/object bindings, section and
English surface content. Every required atom must resolve to an emitting unit or
an explicit non-emitting disposition. Dispositions carry the atom ID, limitation
reason and handling status; they remain in the coverage denominator. A missing unit
without a valid disposition, foreign IDs and changed edges are structural errors.

The initial allowed dispositions are a small versioned set, not a full capability
framework: ambiguous global-tag actor binding, an unsupported relation form, or
source data demonstrably insufficient for realization. Their preconditions are
checked from the inventory and requested format. An arbitrary model claim that a
common prop/category is “unsupported” is not a waiver: it is inconclusive and follows
audit/error handling unless explicitly approved as a limited artifact. An omitted
but expressible fact must fail. The audit reviews disposition justification too. A unit can still lie semantically about the referenced fact: the audit checks
that separate failure class. Structural validation must never be described as proof
of translation accuracy or of correct image rendering.

The deterministic inventory never extracts new facts from old messages. Existing
passage context may remain available for the adapter's current best-effort rendering,
but it cannot create required atoms or retrospectively populate posture/state. There
is no cold-start call to `scene_staging.reconcile_narration` or standalone
`extract_frame` to reconstruct historical state. Unsupported best-effort additions
must not contradict required units; the audit sees the complete assembled artifact.

## Small required set and honest tag limitations

`required_set_version = 1` applies to known eligible facts, not guessed values.

| Fact | Stage 1 classification | Structural check | If output cannot express it unambiguously |
| --- | --- | --- | --- |
| Known visible cast and actor IDs | Required | Exact membership, cardinality, unique scoped actor references; never gender guessed from name | Keep identity in plan; global tags may not distinguish individual subjects. Report that limit, do not claim pixel-level identity assurance. |
| Structured visible clothing tokens/categories | Required when the snapshot supplies them | Item/token atom retained with the original actor association; category changes are audited translations | Generic supported appearance tags may be emitted. Per-actor outfit binding is limited in global tags and reported. Never move an item to another actor to make tags easier. |
| Confirmed prop presence and known owner | Required | Item identity and owner/scene references preserved | Missing prop is a structural error. If supported tags cannot express a category, retain the source fact and explicitly report unrepresented output. |
| Confirmed prop position | Required as a source/plan fact when present | Position atom and prop linkage unchanged; explicit target edges compared, opaque source positions translated and audited | Tag placement may be ambiguous. Report `limited_output_coverage`, keep the render allowed by default for this limitation. |
| Explicit posture and subject/object placement edges | Required when already frozen | Compare the entire subject/predicate/target tuple, not merely the set of IDs | Loss/swapping of the plan edge fails. Loss of unique subject binding in global tags is a visible limitation. |
| Setting prose, mood, lighting prose, fine appearance and clothing detail, unspecified actions | Best effort in v1 | Preserve source references; no invented certainty; audit conflicts with required facts | Mark unsupported/unrepresented details; do not silently promote them to required. |

This resolves the apparent tension in task C. Removing or swapping a **known edge
in the plan** is always an integrity failure. Rendering that intact edge through a
format that cannot bind subjects precisely is a representational limitation. It
would be false to promise both strict full relational fidelity and universally
successful global-tag rendering. The limitation report is part of success output,
not a hidden log entry.

The minimum set's tag-compatible portion must be tested against Neta Lumina's actual
accepted prompting vocabulary. This document does not establish that every arbitrary
prop/relation has a useful Neta tag. Until that evidence exists, its measured support
is unknown; no filename-based capability assertion is permitted. No outfit binding,
unsupported relation or gender inference is invented to satisfy a count.

Statuses remain separate:
- `plan_integrity`: valid / invalid / insufficient_source;
- `semantic_audit`: passed / failed / inconclusive / unavailable / not_run;
- `output_coverage`: complete_for_v1 / limited, with fact IDs and reasons;
- `submission`: allowed / blocked according to the selected handling policy.

A UI must not collapse `valid + limited` into “all scene facts preserved.” Required
facts cannot disappear from the denominator simply because their language or target
format makes them difficult.

## Semantic audit in Stage 1

The audit checks neutral cast, objects, visible clothing categories, positions,
relations, negation and source authority. I can design that general continuity audit;
I cannot design a specialized evaluator intended to preserve explicit sexual details.
Accordingly, a mature marker does not turn its result into a certification of sexual
content completeness. If task B requires that certification, that portion is not
covered by this proposal and must not be represented as accepted.

Within the supported scope, mature-marked snapshots always default to audit ON.
Neutral snapshots also default ON: the same omitted chair, swapped actor or incorrect
translation can become permanently cached there. Cache hits amortize the one-time
cost, and early rollout is the least appropriate time to assume translation quality.
An explicit neutral-only setting may disable the audit, resulting in `not_run`, never
`passed`. There is no automatic downgrade after N successful plans. Mature routing
uses existing authoritative metadata, not a newly invented language-sensitive
classifier; unknown metadata takes the conservative ON path.

The auditor receives the frozen source atoms/evidence, English plan, assembled units,
validated dispositions, source authority labels and final positive/negative text inputs. It does not edit the plan or policy. Its bounded result
identifies affected atom IDs and reasons such as omission, mistranslation, contradiction
or uncertain binding. It can be wrong or correlated with the normalizer, especially
with the same model. Record auditor model/version and preserve an inconclusive status;
a second call is not mathematical independence.

Default handling is strict: `failed`, `inconclusive` or `unavailable` prevents new
submission, keeps any previous image, and gives a visible reason. Configurable warning
mode can proceed with the unresolved status attached to the artifact. A timeout is
not a pass. Formatting limitations from the preceding section remain warnings by
default and must not be mislabeled semantic failures solely because tags are global.
Existing content-policy prohibitions are authoritative in either handling mode.

Audit occurs once per **immutable bundle hash**, including concrete output units.
Changing a translation or artifact creates a new bundle and requires its own audit;
a corrected plan cannot inherit the old pass. Deterministic structural failures may
receive at most one repair before audit. A semantic failure does not trigger an
unbounded retry-until-pass loop; explicit re-preparation creates a new derivation.
No source text, addendum or content-policy instruction is weakened to achieve a pass.

Cost target: a cold successful bundle uses one preparation call plus one audit call;
neutral audit-off uses one. A structural repair adds at most one call. Rerendering the
same bundle with another image seed uses zero preparation/audit calls. First use of a
new profile/format is cold in Stage 1. Tokens and p50/p95 latency must be measured
with the configured Utility model; no fixed latency promise is made.

## Old snapshots: deterministic inventory, no migration wall

All derivation reads `visible_facts` and the validated historical source envelope,
never current NPCs, inventory, clothing or scene state. Source strings and evidence
are not transliterated, lowercased or Unicode-normalized into identity keys.

Existing entity/item IDs remain primary. Facts without IDs receive snapshot-local
IDs derived from the source identity, canonical JSON pointer and occurrence, with a
separate hash of the raw value. Serialize object keys deterministically; preserve
array occurrences and original text. Equal names or equal labels are not evidence
that two entities/objects are identical. Local IDs never create world entities.

| Legacy condition | Result |
| --- | --- |
| Missing field | Unknown/unavailable, not a guessed fact. If cast is absent, its count is unknown, not automatically zero. |
| Empty `clothing_tokens` | No known category atoms. Preserve any `clothing_detail_limited` boundary; never infer undress. |
| Only free-text `clothing` | Preserve one opaque best-effort source fact. Do not pretend code has parsed categories out of prose. Translation is allowed; retrospective wardrobe extraction is not. |
| No staging block | Derive whatever positions/placements actually exist. Missing poses remain unknown. No message re-extraction or live-state fallback. |
| Missing actor/item ID | Assign scoped local IDs; do not join to current objects by name. |
| Prop owner outside the visible cast | Retain the ownership reference without adding the owner to the visible cast. Ownership does not establish presence. |
| Duplicate IDs / dangling relation target | Retain the ambiguity and report insufficient source for that binding. No silent merge or target substitution. |
| Free-text prop position | Keep an opaque position atom linked to that prop; use the audit for its translation. Do not fabricate an engine object from the phrase. |
| Mixed languages | Feed all original field values to normalization with optional language hints. Session language is not an assertion about each field. No `_latin()` gate. |
| No matching snapshot/hash | Keep the existing unavailable result. Never manufacture a past snapshot from today's scene. |

Known typed IDs/edges can be checked structurally. Arbitrary spatial prose, even in
English, cannot have its meaning established by hashing or string containment; its
translation belongs to semantic validation. When no evidence quote exists for a
canonical fact, retain its actual source pointer rather than inventing a quote.

## Stage 1 persistence and lifecycle hooks

Use a bounded, versioned derived registry such as `__visual_preparation__` in existing
session JSON. No new column/table or bulk snapshot migration is required. Bound entry
count and total bytes; eviction removes derived artifacts only. Exclude this registry
from gameplay checkpoint snapshots to prevent multiplication of large cached prompts.
A dedicated table remains a Stage 2 option.

A key contains session/message scope, revision or legacy source hash, snapshot nonce,
source-facts hash, preparation epoch, inventory/normalizer versions, output format,
profile/style/rules fingerprints and existing relevant policy version. No credentials
enter keys or logs. All inference runs outside the DB transaction. Publication rereads
the authorized source and merges into fresh JSON using CAS; never save an old whole
`entity_states` object over a concurrent turn.

The preparation epoch is a fresh UUID on restore/invalidation and is not restored
from a gameplay checkpoint. This closes the ABA case where rewind restores an old
snapshot nonce that an old in-flight job still holds. A source hash check alone is
not enough. Concurrent misses share the existing job/lease mechanism where practical;
a CAS winner establishes the immutable bundle, and a late contender cannot overwrite
it or emit a different uncommitted artifact.

| Existing entry point | Stage 1 responsibility |
| --- | --- |
| `scene_illustrations/generation.py::generate_scene_illustration` | After `owned_context` / `require_snapshot`, freeze inventory and key; release transaction before preparation. |
| `scene_illustrations/render.py::prepare_moment_prompt` | Feature-flag selection; prepare/load bundle and artifact; leave selected format and other asset paths intact. |
| Existing `image_prompt_adapter.py` assembly helpers and `engine/comfyui_images.py` submission seam | For new-path scene jobs only, freeze existing assembly output, audit it, then verify final mapped text-input hashes before submitting. Other assets retain their current behavior. |
| `scene_illustrations/generation.py::_try_attach` / `_attach` | Preserve nonce/hash/CAS protections and validate the preparation epoch for new-path jobs. |
| `regeneration_state.py::refresh_visual_snapshot` | Invalidate the affected message's entries atomically while rotating nonce. |
| `regeneration_state.py::refresh_evidence` | Shared invalidation path used by `regeneration.py::regenerate_latest_message` and `restore_version`. |
| `SessionCheckpointService._build_snapshot` | Exclude disposable derived cache registry from saved gameplay state. |
| `SessionCheckpointService.restore_checkpoint` | Install a fresh preparation epoch and discard incompatible derived entries before commit. |
| `scene_illustrations/snapshots.py::remap_illustrations` | Drop derived cache on copy/import initially; do not trust imported audit passes. |
| `visual_novel/lifecycle.py::copy_vn_state` and `sessions.py` copy flow | Invoke the remapping/invalidation path, not a stale cache copy. |
| `SessionImporter.import_ads` after `restore_messages` | Existing `remap_illustrations` path removes imported derived artifacts; handle the top-level registry explicitly. |
| `snapshots.py::capture_scene_snapshot` and retention pruning | Evict cache entries whose source snapshots no longer exist. |

Restoring an earlier text revision creates a new revision token as today. Preparation
uses the restored message and its matching frozen snapshot, after evidence invalidation;
it never copies current staging into that historical snapshot. An old in-flight result
must fail publication after revision change or rewind, including same-text ABA cases.

## Growing the required set without wiping translations

Version inventory schema, normalization, required set and artifact format separately.
The required-set version is part of the validation/artifact identity, not a reason to
delete every English translation. An immutable v1 bundle remains explicitly v1.

On demand for v2, deterministically derive the v2 inventory from the same frozen JSON.
Reuse an existing atom translation only when raw source hash, context/binding identity
and normalization policy match. Validate/reassemble a new v2 bundle; normalize only
new or invalid atoms where the implementation can safely do so. Re-audit changed
bundles under the required audit policy. Missing historical data stays unavailable;
it cannot be backfilled from the current scene. V1 and v2 may coexist until ordinary
cache eviction. Stage 1 does not require cross-session or cross-message reuse.

## Stage 1 release gate and compatibility

A separate preparation-path flag defaults to Legacy throughout development. New-path
structural failures never silently fall back to Legacy and receive a “passed” badge.
Only after the acceptance gate passes does the scene default switch and `_latin()`
stop governing new-path scene validation. This is independent of Stages 2 and 3.

Required acceptance:

1. EN/RU/FR × tags/description/hybrid, extended with JA/DE/PL and mixed-script fields.
   Correct supported translations have zero false refusals in the finite curated
   suite. No Cyrillic/CJK facts disappear from eligibility, and no French/Polish
   phrase is demanded verbatim in English output.
2. Mutation tests remove/swap known subjects, clothing ownership, props, position
   bindings and relation edges. Invalid normalized tuples or missing output units
   are detected. Mutations inside opaque English surface text are separate audit
   tests; structural checks do not falsely claim to detect their semantics.
3. Intact but ambiguously represented tag relations complete with validated non-emitting
   dispositions or explicit representation limitations, not silent full coverage and
   not a cascade of hard render failures. Golden tests cover this separately from plan
   corruption. A fabricated “unsupported” waiver for an expressible fact must fail.
   Prefix/suffix contradiction and post-audit workflow text mutation tests must also
   fail; a hash in the cache key alone is not a semantic check.
4. Mature-flag routing uses default audit ON within the supported neutral audit scope;
   neutral ON/OFF, failure/warning modes, timeouts, repair limits and audit invalidation
   have explicit tests. No audit result certifies out-of-scope detail preservation.
5. Existing avatar, cover, portrait and other `image_prompt_adapter` consumers remain
   on their current entry point. Add scene preparation as a private/new entry point;
   do not change the public adapter return type or default behavior. Contract tests
   verify those consumers and existing policy/addendum selection/injection decisions.
6. Existing tags, prose and hybrid formats remain selectable. Real Neta Lumina trials
   assess supported neutral tags and relation limitations; mocked schema tests cannot
   certify checkpoint quality. EN parity is measured on meaning and visible coverage,
   not preservation of the old erroneous substring/negation behavior.
7. No narrative/evidence changes, no historical state re-extraction, no bulk migration.
   Legacy fixtures, cache races, revision/rewind ABA, copy/import and eviction pass.
8. Identical persisted bundle and profile/policy inputs give identical prompt bytes
   over 100 rerenders and zero preparation/audit calls. Independent fresh LLM
   derivations are not promised identical merely because temperature is zero.
9. Report all eligible required source facts in the denominator; separately report
   unknown source data, semantic uncertainty, policy exclusions and output limitations.
   Break down results by source-language hint and requested format.
10. Measure a complete current test baseline before implementation acceptance; compare
    exact failures and detect new regressions. A historical passing count is not proof.

**Measured baseline status:** on revision `3f46c8bf`, ran the existing test runner
against `tests -q --maxfail=1`, bounded by `timeout 120`. It exited with code 124
(timeout), with progress reaching approximately 10% and no final pytest summary.
This is an incomplete run, not a passing baseline and not evidence of a regression.
A separate collection-only run succeeded: **2,655 tests collected in 1.42 seconds**.
Collection success is not test execution success. The full release gate remains open.
The next baseline run needs per-test timing and
identification of the in-flight test, then completion under the project's normal
suite configuration. No production fixes or test skips were introduced to make a
baseline look green.

No application code, database schema or prompt policy has been changed for this
proposal. Implementation remains a separate step after review.
