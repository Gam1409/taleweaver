# Shared visual plans and default scene preparation

This release completes the reusable compiler stage. Saved visual plans are now the
standard preparation path for neutral VN moment illustrations. The Legacy selector
has been removed. Existing `visual_preparation: legacy` settings and older API
payloads upgrade to `plan` without resetting pace or audit preferences. No data
migration or provider reconfiguration is required.

NSFW-enabled sessions keep their existing preparation automatically, without an
exposed mode selector. Their prompts, addenda and injection rules are unchanged.
This compatibility boundary preserves the user's explicit NSFW scope exclusion;
it is not an available fallback after a failed neutral plan check.

## Translation and compilation

A normalization request produces one English plan containing description and tag
surfaces for every eligible source atom. Both surfaces keep the same subject,
predicate, target, source-value hash and atom ID. Both variants are structurally
validated before persistence, including the currently unused variant.

The deterministic compilers are:

- **Description:** bound English sentences for each fact.
- **Tags:** comma-separated tags, with declared global-binding limitations.
- **Hybrid:** required facts remain in bound prose; optional appearance/context
  uses tags when available. Missing optional tags can retain their prose surface.

Each compiler produces a versioned capability descriptor and source map, in
addition to the selected units and body. No compiler claims regional conditioning,
precise pixel geometry or model-specific pose control. Additional model families
can introduce separately versioned capabilities without relabeling today's generic
English renderer as universally precise.

## Cache compatibility and cost

The normalization key excludes output format, image model, seed, workflow graph,
prefix and suffix. It includes source/revision/epoch identity, inventory and
normalization versions, English policy instructions, artistic style, word budget
and Small/Utility settings. Only compatible policies reuse the plan; different
vocabulary/instructions or budgets prepare a fresh plan.

The final artifact key additionally includes the compiler version and full image
profile/policy configuration. A new suffix, format or workflow therefore cannot
inherit another artifact's audit.

| Operation | Normalization calls | Audit calls with auditing enabled |
| --- | --- | --- |
| First scene/profile | 1 (one structural repair permitted) | 1 |
| Compatible new format/profile | 0 | 1 |
| New suffix/prefix | 0 | 1 |
| Exact artifact / seed-only rerender | 0 | 0 |
| Changed normalization policy | 1 | 1 |
| Explicit rebuild | 1 | 1 |

Auditing disabled means zero audit calls, never a reported pass. The audit compares
original source facts with the selected compiled output and final positive/negative
text. Unused surface translations do not receive a blanket semantic pass; they are
checked when used in a new artifact. Existing structural failure, audit block/warn,
provider text fencing and revision/rewind protections remain in force.

English plans and final artifacts share the existing bounded registry (eight derived
records, 2 MiB). Eviction can require another cold normalization. No cross-message
or cross-session translation reuse is attempted. Snapshot pruning, import/copy,
checkpoint restoration, regeneration and explicit rebuild invalidate both layers.
Old v1 artifacts are not trusted under v2 keys; already generated images remain.

## Inspectable output provenance

Every fact remains in the source-map denominator, including non-emitting
limitations. Emitted entries carry exact body spans. Final positive-prompt spans
are recorded only when the complete body has one unambiguous occurrence in the
submitted prompt. Trimming, duplication or transformation yields an unavailable
final mapping rather than guessed offsets. Offsets are Unicode code points;
frontend rendering handles supplementary characters accordingly.

**Generation details → Saved visual plan** shows compiler format, audit status,
reuse, emitted/total facts and actual final-prompt excerpts. This is diagnostic
coverage, not proof of translation correctness or image quality. The visual trace
also records capabilities, plan hash, source map and artifact hash.

## Validation boundary

Tests cover six source languages, all three formats, missing/changed bindings,
unused variant corruption, tag limitations, duplicate text and Unicode offsets,
compatible profile reuse, per-artifact audit, policy invalidation, automatic old
settings upgrades and the unchanged NSFW compatibility route. Mock model responses
exercise software contracts; real checkpoint calibration remains a separate
empirical check. The default change is explicitly user-authorized and does not
claim that a language-model auditor or image generator is infallible.

The eligible required fact taxonomy remains v1. Expanding the game's canonical
facts or adding new extractors is a separate gameplay change; this release does
not fabricate historical emotions, limb positions or clothing state to populate
new fields.

## Verification record

All 2,722 collected backend tests passed. The initial whole-suite run reached its
300-second limit; all tests in its 131 fully completed files (1,555 tests) were
verified against the collection. The remaining 121 files, including the interrupted
file in full, passed in four groups (341 + 214 + 304 + 308 tests). No tests were
skipped to obtain this result. Frontend type checking, production build, 15 VN UI
tests, Ruff and scoped MyPy also passed.
