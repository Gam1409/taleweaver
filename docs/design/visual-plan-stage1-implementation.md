# Saved visual plans: Stage 1 implementation

The first stage is opt-in for Visual Novel moment illustrations. Existing sessions
keep **Current preparation**. Enable **Saved visual plan** in adventure narration
settings. The image workflow still chooses description, tags or hybrid format.
The plan output language is English; frozen source values retain their original
language. Unconfigured/non-Comfy providers use description format.

## Behavior

- Inventory uses only the selected message's frozen public facts. It never fills
  historical gaps from today's NPC state or re-extracts old narration.
- One structured Small/Utility call emits actual text units bound to source IDs,
  subjects, predicates, targets and value hashes. Exactly one unit or permitted
  limitation must account for each atom. One structural repair is allowed.
- Required v1 atoms cover cast, supplied posture/position, structured worn tokens,
  placement edges and props. Appearance, free-form clothing, setting, lighting and
  visible action are best effort. Missing clothing stays unknown.
- The assembler preserves the selected format. Global tags can lose per-actor
  binding; a visible limited-coverage notice reports this. A hash/ID match does not
  prove translation correctness.
- Audit defaults on, with blocking on failed, inconclusive or unavailable checks.
  The audit sees original atoms, English units, limitations and the final positive
  and negative text after the existing prefix/suffix/style assembly. Users can
  choose warning mode or disable the neutral audit; neither reports a pass.
- Only negative text actually supported by the provider is audited. ComfyUI's
  mapped text inputs are checked again immediately before job submission. This
  does not certify arbitrary unbound graph nodes, model internals or image pixels.
- A successful cold bundle uses two LLM calls (one with audit off); rerendering a
  cached bundle uses zero. Profile/format/configuration changes prepare a new
  bundle. Audit failures are cached too; **Rebuild visual plan and illustrate**
  explicitly replaces the derivation.

## Scope and lifecycle

NSFW prompt sources and addenda are unchanged. Stage 1 explicitly rejects plan
preparation for NSFW-enabled sessions and directs them to Current preparation.
No audit result certifies explicit sexual detail preservation.

Up to eight bundles / 2 MiB live in the session's disposable JSON registry, without
a database migration. Publication reloads authorized state, uses a short session
lease plus CAS, and never overwrites unrelated changes. Concurrent contenders use
the first committed artifact. Revision/snapshot identity, preferences, generation
epoch and profile fingerprints fence stale results.

Checkpoint snapshots exclude this cache; restore installs a fresh epoch. Copy and
import discard it. Rewriting a reply or changing preparation preferences clears it.
Rebuild currently clears all derived bundles in this session, so other moments
may incur cold preparation afterward. Snapshot pruning also prunes derived entries.
Canonical game facts are never changed by preparation or audit.

## Validation and remaining acceptance

Automated tests cover Cyrillic/Japanese source values, all three formats, missing
and swapped bindings, declared tag limits, audit errors, cache reuse, explicit
rebuild, stale publication/attachment, import remapping, checkpoint lifecycle,
final prefix/suffix auditing and post-audit text mutation. Mocked provider tests
exercise control flow; they do not measure model accuracy. A 100-seed assembly
check verifies byte-identical text without adaptation.

Before enabling by default, calibrate with real Small/Utility and image models on
multilingual scene fixtures. Visual trace records structural differences, audit
issues/status, model/version, cache hits, preparation time and final artifact hash;
existing query telemetry records model usage. No claim of stable poses in generated
pixels follows from these software tests. Full reusable compilers and shared plans
across output profiles remain Stage 2.
