# NSFW required atoms (Stage 3)

Stage 3 of the multilingual visual contract adds a **required atomic subset for
explicit scenes** on the retained NSFW illustration route. It is a **check, not
a prompt**: NSFW prompt construction, mature addenda and content policy are
unchanged. The module verifies that explicit facts the staging extraction
grounded in the narration survive into the final English image prompt, and it
fails visibly when they do not.

## Constraints honored

- NSFW prompt text, policy addenda and injection rules are not modified; the
  content policy remains authoritative.
- Language-agnostic: session-language evidence is stored byte-exact and never
  compared against the English prompt. Participant identity is checked through
  verbatim character names (proper nouns survive translation by contract).
- Zero additional LLM calls at message time: explicit atoms ride the existing
  scene-staging extraction call. The render-time check is deterministic code
  inside the existing bounded retry loop.
- Determinism: the check depends only on the frozen message snapshot, the
  versioned keyword table and the final prompt body.

## Data flow

1. **Extraction (message time).** `SceneExtraction` gains an optional
   `explicit` list. Each `ExplicitDelta` carries a fixed `category`, the
   `participants` (present character IDs, 1–6) and an `evidence` quote that
   must appear verbatim in the narration. The instructions ask for acts that
   are **ongoing or completed at the final instant**, echoing a continuing act
   from `previous_staging` with the continuation quote. Silence reports
   nothing; requests, negations and hypotheticals are never reported.
2. **Validation (message time).** `reconcile()` drops atoms with unknown
   participants or failed quote checks individually, counts them in
   `explicit_rejected` and never blocks posture/placement facts on that
   account. Valid atoms are stored fresh per message (acts are states, not
   accumulated deltas) with `evidence` and `source_hash`.
3. **Freezing (snapshot).** When the staging result matches the completed
   message (`source_hash` + scene), the VN runtime copies `explicit` into the
   snapshot facts, and `_visible_facts` preserves a sanitized, bounded copy
   (max 8 atoms, participants capped, evidence capped at 800 chars). Snapshots
   older than this release carry no `explicit` key.
4. **Check (render time, NSFW route only).** `prepare_moment_prompt` injects
   an explicit-content fidelity clause into the existing policy instructions
   and runs `nsfw_guard.differences(body, atoms)` per attempt alongside the
   literal fidelity diff. Missing acts or participants join the correction
   feedback of the bounded retry. After the retry budget:
   - `block`: the render is refused with an explicit error (no image).
   - `warn` (default, shadow): the image proceeds; the failure is recorded in
     generation details and the visual trace.

## Required subset v1

| Atom | How it is checked | If unverifiable / unexpressible |
| --- | --- | --- |
| Explicit act category (kissing, undressing, manual, oral, vaginal, anal, masturbation, grinding) | Versioned English keyword table over the final prompt body (word-boundary or safe-prefix stems) | Missing category keyword = missing required atom → retry, then mode-dependent failure. Euphemisms outside the table are a documented false-pass risk, mitigated by shadow data before `block` is enabled. |
| Act participants (who is engaged, by present cast ID) | Verbatim participant names must appear in the body; the fidelity clause instructs name preservation | Missing name = missing required atom. Acts with characters absent from the staged cast are dropped at extraction. |
| Ongoing act continuation | Extractor re-reports continuing acts with a fresh quote; no client-side accumulation in v1 | A missed continuation degrades to `not_run`/weaker coverage, visible in details. |

Per-act role binding (who performs what on whom) is **not** required in v1:
global tag binding limits make it unenforceable in tag formats, and prose
formats express it only semantically. It stays a visible limitation. Undress
state and pose details are delegated to the clothing system and best-effort
narration; their loss is a warning-level concern, not a required-atom failure.

## Configuration and acceptance

`VnSettings.nsfw_guard` (default `warn`): `off` skips injection and checking;
`warn` records failures without blocking; `block` refuses the render. The
guard mirrors the image addendum gate and activates **only when adult content
is enabled in the adventure AND the selected Visual profile enables mature
themes** (`select_profile(options).mature_themes`); otherwise the status is
`not_run`. A session whose visual layer is configured to render non-explicit
images never receives explicit-content requirements or explicit-atom blocks.
The default is shadow so that keyword-table precision can be observed on real
traffic before any image is refused. Flipping to `block` is an explicit
settings change; changing the mode does not invalidate saved visual plans
(the plan path never consumes explicit atoms). Generation details expose
`nsfw_guard: {mode, status, checked, missing, version}`; status is `not_run`
when the snapshot carries no atoms — `not_run` is never reported as `passed`.

## Compatibility

- Neutral plan route: `visual_plan.inventory` ignores unknown fact keys;
  snapshots may now carry `explicit` without any effect on plans, caches or
  audits.
- Old sessions and imported archives: no staging match or no `explicit` key →
  status `not_run`, shadow warnings only, renders unchanged.
- Legacy NSFW behavior (prompt assembly, addenda, provider gating) is
  byte-identical; only an additive check and additive instruction text are
  introduced on the route that already runs fidelity checks.

## Keyword table versioning

`nsfw_guard.VERSION` identifies the category keyword table. Refinements (new
stems, pruning false-positive-prone stems) bump the version and are recorded
in generation details. There is no plan cache to invalidate; the version only
makes check results auditable over time.

## Test plan

Unit: category detection, weakening detection (required act replaced by a
milder one), participant loss, verbatim-name pass, multiple acts, empty input.
Staging: evidence quote validation, unknown-participant rejection, posture
isolation from explicit rejections, backward-compatible empty explicit.
Snapshot: bounded sanitization, key absence when empty. Render (mocked
adapter): block raises after the retry budget, warn proceeds and records,
off skips injection, `not_run` without atoms, neutral route unaffected,
requirements text injected only when atoms exist. Mutation matrix: drop atom,
swap category to a milder one, drop a participant — each detected; correct
paraphrase with required stems — passed; session-language evidence never
compared against the English body.
